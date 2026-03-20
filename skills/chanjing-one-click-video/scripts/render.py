"""
混合渲染：整篇 TTS → 按分镜切 WAV → 数字人（音频驱动）/ AI 文生视频 + 切段合成 → ffmpeg 拼接。
环境变量与业务约束见同级 SKILL.md；本模块仅实现编排与 ffmpeg。
"""

from __future__ import annotations
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from schemas import VideoPlan, ScriptResult, StoryboardResult, RenderResult, Scene
from utils import get_logger, timed

logger = get_logger("render")

AVATAR_GENDER       = os.environ.get("CHANJING_AVATAR_GENDER", "Female").lower()
FIGURE_SOURCE       = os.environ.get("CHANJING_FIGURE_SOURCE", "auto").strip().lower()
AI_VIDEO_MODEL      = os.environ.get("AI_VIDEO_MODEL", "Doubao-Seedance-1.0-pro")
OUTPUT_W            = 1080
OUTPUT_H            = 1920
FFMPEG_TIMEOUT      = 1800   # 30 min max per ffmpeg call（CDN 下载慢）
SCENE_MAX_WORKERS   = 5      # 最多并行渲染几个镜头
CDN_MAX_CONCURRENT  = 1      # CDN 串行下载（避免 Chanjing CDN 限流）

# 全局信号量：限制同时进行 CDN 下载（ffmpeg 读取远程 URL）的数量
_cdn_semaphore = threading.Semaphore(CDN_MAX_CONCURRENT)


def _probe_video_encoder() -> tuple[str, list[str]]:
    """探测硬件编码器（videotoolbox / nvenc / qsv / amf），失败则用 libx264。"""
    candidates = [
        ("h264_videotoolbox", ["-q:v", "65"]),
        ("h264_nvenc",        ["-preset", "p4", "-cq", "23"]),
        ("h264_qsv",          ["-preset", "medium"]),
        ("h264_amf",          ["-quality", "balanced"]),
    ]
    test_input = ["-f", "lavfi", "-i", "color=c=black:s=128x128:d=0.1:r=30"]
    for codec, quality_args in candidates:
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error",
                 *test_input,
                 "-c:v", codec, *quality_args,
                 "-f", "null", "-"],
                capture_output=True, timeout=10,
            )
            if r.returncode == 0:
                logger.info("视频编码器: %s（硬件加速）", codec)
                return codec, quality_args
        except Exception:
            continue
    logger.info("视频编码器: libx264（CPU 软件编码）")
    return "libx264", ["-preset", "fast", "-crf", "23"]


_VIDEO_CODEC, _VIDEO_QUALITY_ARGS = _probe_video_encoder()


def _skills_root() -> Path:
    d = os.environ.get("CHAN_SKILLS_DIR", "")
    if not d:
        raise RuntimeError(
            "CHAN_SKILLS_DIR 未设置。请指向 chan-skills 仓库根目录：\n"
            "  export CHAN_SKILLS_DIR=/path/to/chan-skills"
        )
    p = Path(d)
    if not p.is_dir():
        raise RuntimeError(f"CHAN_SKILLS_DIR 路径不存在: {p}")
    return p


def _script(skill: str, name: str) -> Path:
    root = _skills_root()
    for candidate in [
        root / "skills" / skill / "scripts" / name,
        root / skill / "scripts" / name,
    ]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"找不到脚本 {skill}/scripts/{name}")


def _run(script: Path, args: list[str], label: str = "") -> str:
    """运行脚本，返回 stdout（strip）。失败时抛出 RuntimeError。"""
    cmd = [sys.executable, str(script)] + args
    logger.debug("▷ %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"{label or script.name} 失败 (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    out = result.stdout.strip()
    logger.debug("◁ %s → %s", label or script.name, out[:120])
    return out


def _ffmpeg(*args: str, label: str = "") -> None:
    """运行 ffmpeg，失败时抛出 RuntimeError。超时 30 分钟（覆盖大文件 CDN 下载场景）。"""
    cmd = ["ffmpeg", "-y", *args]
    logger.debug("ffmpeg %s", " ".join(args[:8]))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg {label} 失败: {result.stderr[-500:]}"
        )


def _get_audio_duration(path: Path) -> float:
    """用 ffprobe 获取音频时长（秒）。"""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


class _noop_ctx:
    """空上下文管理器，用于本地文件跳过信号量。"""
    def __enter__(self): return self
    def __exit__(self, *_): pass


def _normalize(src: str | Path) -> Path:
    """
    将片段统一编码为 1080x1920 h264+aac，返回新临时文件。
    src 可以是本地路径或 HTTP URL。
    远程 URL 使用 CDN 并发信号量，避免 Chanjing CDN 限流。
    """
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    out.close()
    src_str = str(src)
    is_remote = src_str.startswith("http")
    ctx = _cdn_semaphore if is_remote else _noop_ctx()
    with ctx:
        _ffmpeg(
            "-i", src_str,
            "-vf", (
                f"scale={OUTPUT_W}:{OUTPUT_H}:force_original_aspect_ratio=decrease,"
                f"pad={OUTPUT_W}:{OUTPUT_H}:(ow-iw)/2:(oh-ih)/2:color=black"
            ),
            "-c:v", _VIDEO_CODEC, *_VIDEO_QUALITY_ARGS,
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            out.name,
            label="normalize",
        )
    return Path(out.name)


def _composite_video_audio(video: str | Path, audio: str | Path) -> Path:
    """将音频叠加到视频上（循环视频以匹配音频长度）。
    video 可以是 URL；audio 通常为本地 WAV 文件。
    仅在 video 为远程 URL 时使用 CDN 信号量。
    """
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    out.close()
    is_remote = str(video).startswith("http")
    ctx = _cdn_semaphore if is_remote else _noop_ctx()
    with ctx:
        _ffmpeg(
            "-stream_loop", "-1", "-i", str(video),
            "-i", str(audio),
            "-map", "0:v", "-map", "1:a",
            "-vf", (
                f"scale={OUTPUT_W}:{OUTPUT_H}:force_original_aspect_ratio=decrease,"
                f"pad={OUTPUT_W}:{OUTPUT_H}:(ow-iw)/2:(oh-ih)/2:color=black"
            ),
            "-c:v", _VIDEO_CODEC, *_VIDEO_QUALITY_ARGS,
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-shortest",
            out.name,
            label="composite",
        )
    return Path(out.name)


def _concat_clips(clips: list[Path]) -> Path:
    """用 ffmpeg filter_complex concat 合并所有片段。"""
    if len(clips) == 1:
        return clips[0]

    out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    out.close()

    inputs: list[str] = []
    for clip in clips:
        inputs += ["-i", str(clip)]

    n = len(clips)
    filter_str = "".join(f"[{i}:v][{i}:a]" for i in range(n))
    filter_str += f"concat=n={n}:v=1:a=1[v][a]"

    _ffmpeg(
        *inputs,
        "-filter_complex", filter_str,
        "-map", "[v]", "-map", "[a]",
        "-c:v", _VIDEO_CODEC, *_VIDEO_QUALITY_ARGS,
        "-c:a", "aac",
        out.name,
        label="concat",
    )
    return Path(out.name)


def _stub_render(plan: VideoPlan, storyboard: StoryboardResult) -> RenderResult:
    logger.info("[STUB] 跳过真实渲染，返回占位结果")
    return RenderResult(
        video_url="https://example.com/stub-video.mp4",
        cover_url="https://example.com/stub-cover.jpg",
        tts_urls=[f"https://example.com/stub-tts-{s.scene_id}.mp3" for s in storyboard.scenes],
        scene_video_urls=[f"https://example.com/stub-scene-{s.scene_id}.mp4" for s in storyboard.scenes],
        render_path="stub",
        degrade_log=[],
    )


@dataclass
class ResolvedFigureCandidates:
    """数字人候选 (person_id, figure_type, audio_man_id)，按顺序重试。"""

    candidates: list[tuple[str, str, str]]
    source: str  # common | customised

    @property
    def primary(self) -> tuple[str, str, str]:
        return self.candidates[0]

    def audio_man_for_tts(self) -> str:
        """整篇 TTS 音色：环境变量优先，否则首选形象的 audio_man。"""
        env_voice = os.environ.get("CHANJING_VOICE_ID", "").strip()
        if env_voice:
            return env_voice
        _pid, _ft, am = self.primary
        if not am:
            raise RuntimeError(
                "当前首选数字人未返回 audio_man_id，且未设置 CHANJING_VOICE_ID。"
                "请设置 CHANJING_VOICE_ID，或换一个有绑定音色的公共数字人。"
            )
        return am


def _list_figures_payload(source: str) -> dict:
    raw = _run(
        _script("chanjing-video-compose", "list_figures"),
        ["--source", source, "--json"],
        label=f"list_figures {source}",
    )
    return json.loads(raw)


def _parse_figure_rows(payload: dict, source: str) -> list[dict]:
    """从 list_figures --json 解析为统一行结构。"""
    inner = payload.get("data") or {}
    items = inner.get("list", []) or []
    rows: list[dict] = []
    if source == "common":
        for item in items:
            for figure in item.get("figures", []) or []:
                rows.append({
                    "person_id": item.get("id", ""),
                    "figure_type": (figure.get("type") or "").strip(),
                    "audio_man_id": (item.get("audio_man_id") or "").strip(),
                    "gender": (item.get("gender") or "").lower(),
                    "name": (item.get("name") or "").strip(),
                })
    else:
        for item in items:
            rows.append({
                "person_id": (item.get("id") or "").strip(),
                "figure_type": (item.get("figure_type") or "").strip(),
                "audio_man_id": (item.get("audio_man_id") or "").strip(),
                "gender": (item.get("gender") or "").lower(),
                "name": (item.get("name") or "").strip(),
            })
    return [r for r in rows if r["person_id"]]


def _apply_voice_override(rows: list[dict]) -> list[dict]:
    override = os.environ.get("CHANJING_VOICE_ID", "").strip()
    if not override:
        return rows
    out = []
    for r in rows:
        r2 = dict(r)
        r2["audio_man_id"] = override
        out.append(r2)
    return out


def _dedupe_candidate_order(rows: list[dict], primary: dict) -> list[dict]:
    """primary 在前，其余按原顺序去重 (person_id, figure_type)。"""

    def key(r: dict) -> tuple[str, str]:
        return r["person_id"], r["figure_type"]

    seen = {key(primary)}
    ordered = [primary]
    for r in rows:
        k = key(r)
        if k in seen:
            continue
        seen.add(k)
        ordered.append(r)
    return ordered


def _resolve_figure(plan: VideoPlan) -> ResolvedFigureCandidates:
    """list_figures → 校验显式 id → 排序候选；CHANJING_VOICE_ID 覆盖各候选音色。"""
    explicit_person = (
        (plan.avatar_id or "").strip()
        or os.environ.get("CHANJING_AVATAR_ID", "").strip()
        or os.environ.get("CHANJING_PERSON_ID", "").strip()
    )
    explicit_figure = os.environ.get("CHANJING_FIGURE_TYPE", "").strip()

    sources: list[str] = []
    if FIGURE_SOURCE == "common":
        sources = ["common"]
    elif FIGURE_SOURCE == "customised":
        sources = ["customised"]
    else:
        sources = ["common", "customised"]

    last_err: str | None = None
    rows: list[dict] = []
    used_source = "common"

    for src in sources:
        try:
            payload = _list_figures_payload(src)
        except Exception as exc:
            last_err = str(exc)
            logger.warning("list_figures %s 失败: %s", src, exc)
            continue
        rows = _apply_voice_override(_parse_figure_rows(payload, src))
        used_source = src
        if rows:
            break
        logger.warning("list_figures %s 返回 0 条可用形象", src)

    if not rows:
        hint = (
            "无法获取可用数字人列表。请确认：1) 账号已开通视频合成与公共/定制数字人；"
            "2) 运行 `python skills/chanjing-video-compose/scripts/list_figures --source common --json` 自查；"
            "3) 如需只用定制形象，设置 CHANJING_FIGURE_SOURCE=customised。"
        )
        if last_err:
            hint += f" 最近一次接口错误: {last_err}"
        raise RuntimeError(hint)

    primary: dict | None = None
    if explicit_person:
        matches = [r for r in rows if r["person_id"] == explicit_person]
        if explicit_figure:
            matches = [r for r in matches if r["figure_type"] == explicit_figure]
        if not matches:
            raise RuntimeError(
                f"数字人校验失败：person_id={explicit_person!r} 不在当前列表中（来源={used_source}），"
                f"或形态 CHANJING_FIGURE_TYPE={explicit_figure!r} 不匹配。"
                f"当前共 {len(rows)} 条形象。请用 list_figures --source {used_source} --json 核对 id 与 figure_type；"
                f"合成失败时会自动依次尝试列表中的其它形象。"
            )
        primary = matches[0]
        logger.info(
            "已校验指定数字人: person_id=%s, figure_type=%s, source=%s",
            primary["person_id"], primary["figure_type"] or "(默认)", used_source,
        )
    else:
        preferred = [r for r in rows if AVATAR_GENDER in r["gender"]]
        primary = preferred[0] if preferred else rows[0]
        logger.info(
            "自动选择数字人: person_id=%s, figure_type=%s, source=%s（性别偏好=%s）",
            primary["person_id"], primary["figure_type"] or "(默认)", used_source, AVATAR_GENDER,
        )

    ordered = _dedupe_candidate_order(rows, primary)
    candidates = [(r["person_id"], r["figure_type"], r["audio_man_id"]) for r in ordered]
    logger.info(
        "数字人候选共 %d 个（合成失败时将依次尝试其它 id）",
        len(candidates),
    )
    return ResolvedFigureCandidates(candidates=candidates, source=used_source)


def _generate_full_tts(full_script: str, audio_man_id: str) -> Path:
    """整篇一次 TTS → 本地 WAV。"""
    logger.info("[TTS] 生成整篇完整音频（一次性）…")
    task_id = _run(
        _script("chanjing-tts", "create_task"),
        ["--audio-man", audio_man_id, "--text", full_script],
        label="full tts create",
    )
    audio_url = _run(
        _script("chanjing-tts", "poll_task"),
        ["--task-id", task_id],
        label="full tts poll",
    )
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    out.close()
    with _cdn_semaphore:
        _ffmpeg(
            "-i", audio_url,
            "-c:a", "copy",
            out.name,
            label="download full tts",
        )
    logger.info("[TTS] 完整音频已下载: %s (url=%s)", out.name, audio_url[:60])
    return Path(out.name)


def _split_audio_by_scenes(wav_path: Path, scenes: list[Scene]) -> list[Path]:
    """按各镜口播字数比例切分 WAV，长度与 scenes 一致。"""
    total_duration = _get_audio_duration(wav_path)
    total_chars = sum(len(s.voiceover) for s in scenes) or 1

    logger.info(
        "[Split] 总音频时长 %.2fs，共 %d 镜头，总字符数 %d",
        total_duration, len(scenes), total_chars,
    )

    segments: list[Path] = []
    offset = 0.0
    for i, scene in enumerate(scenes):
        ratio = len(scene.voiceover) / total_chars
        seg_duration = total_duration * ratio
        # 最后一段延伸到结尾，避免浮点累积误差截断
        if i == len(scenes) - 1:
            seg_duration = total_duration - offset

        out = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        out.close()
        _ffmpeg(
            "-i", str(wav_path),
            "-ss", f"{offset:.3f}",
            "-t", f"{seg_duration:.3f}",
            "-c:a", "copy",
            out.name,
            label=f"split scene{scene.scene_id}",
        )
        segments.append(Path(out.name))
        logger.debug(
            "  Scene %d: offset=%.2fs duration=%.2fs (%d chars)",
            scene.scene_id, offset, seg_duration, len(scene.voiceover),
        )
        offset += seg_duration

    return segments


def _upload_scene_audio(wav_path: Path) -> str:
    """上传 WAV 文件到蝉镜文件存储，返回 file_id。"""
    file_id = _run(
        _script("chanjing-video-compose", "upload_file"),
        ["--service", "make_video_audio", "--file", str(wav_path)],
        label="upload scene audio",
    )
    return file_id.strip()


def _render_dh_scene_once(
    person_id: str,
    figure_type: str,
    audio_man_id: str,
    scene: Scene,
    wav_path: Path | None = None,
) -> Path:
    """wav_path 有则音频驱动，无则文本驱动（降级）。"""
    task_args = ["--person-id", person_id, "--subtitle", "show"]
    if figure_type:
        task_args.extend(["--figure-type", figure_type])

    if wav_path is not None:
        logger.info(
            "  [DH] Scene %d: 上传音频 → 音频驱动（person=%s figure=%s）…",
            scene.scene_id,
            person_id[:8] + "…" if len(person_id) > 8 else person_id,
            figure_type or "-",
        )
        file_id = _upload_scene_audio(wav_path)
        task_args.extend(["--audio-file-id", file_id])
    else:
        logger.info(
            "  [DH] Scene %d: 文本驱动（降级）person=%s figure=%s…",
            scene.scene_id,
            person_id[:8] + "…" if len(person_id) > 8 else person_id,
            figure_type or "-",
        )
        if not audio_man_id:
            raise RuntimeError("文本驱动需要 audio_man_id，请设置 CHANJING_VOICE_ID 或换用有默认音色的形象")
        task_args.extend(["--text", scene.voiceover, "--audio-man", audio_man_id])

    video_id = _run(
        _script("chanjing-video-compose", "create_task"),
        task_args,
        label=f"create_task scene{scene.scene_id}",
    )

    video_url = _run(
        _script("chanjing-video-compose", "poll_task"),
        ["--id", video_id],
        label=f"poll_task scene{scene.scene_id}",
    )
    logger.info("  [DH] Scene %d URL 就绪: %s", scene.scene_id, video_url[:60])
    return _normalize(video_url)


def _render_dh_scene(
    resolved: ResolvedFigureCandidates,
    scene: Scene,
    wav_path: Path | None = None,
) -> Path:
    """按形象列表顺序重试；音频驱动时只换人、不换 WAV。"""
    errors: list[str] = []
    for i, (person_id, figure_type, audio_man_id) in enumerate(resolved.candidates):
        try:
            return _render_dh_scene_once(
                person_id, figure_type, audio_man_id, scene, wav_path
            )
        except Exception as exc:
            msg = f"候选{i + 1}/{len(resolved.candidates)} person_id={person_id!r} figure={figure_type!r}: {exc}"
            logger.warning("  [DH] Scene %d 合成失败，将尝试下一形象: %s", scene.scene_id, msg)
            errors.append(msg)

    detail = "；".join(errors[:3])
    if len(errors) > 3:
        detail += f" …（共{len(errors)}次失败）"
    raise RuntimeError(
        f"数字人镜头 Scene {scene.scene_id} 在尝试 {len(resolved.candidates)} 个形象后仍失败。"
        f"可检查 person_id 是否仍有效、账号权限或稍后重试。详情: {detail}"
    )


# ---------------------------------------------------------------------------
# 镜头渲染：AI 生成画面 + 预切割音频
# ---------------------------------------------------------------------------

def _render_ai_scene(scene: Scene, wav_path: Path) -> Path:
    """
    生成 AI 画面片段：
    1. 提交 AI 视频任务并等待
    2. ffmpeg composite（AI 视频 URL + 本地 WAV）→ 本地 mp4
    不调用独立 TTS，直接使用从整篇音频切割出的本地 WAV。
    """
    logger.info("  [AI] Scene %d: 提交 AI 视频任务…", scene.scene_id)
    # 模型要求 video_duration ∈ [5, 10]；较长镜头由 ffmpeg loop 补足
    ai_duration = max(5, min(10, scene.duration_sec))
    ip = (scene.image_prompt or "").strip()
    iv = (scene.i2v_prompt or "").strip()
    vp = (scene.visual_prompt or "").strip()
    prompt = " ".join(p for p in (ip, iv) if p) or vp or (
        "vertical 9:16 documentary b-roll, soft motion, no text"
    )
    ai_unique_id = _run(
        _script("chanjing-ai-creation", "submit_task"),
        [
            "--creation-type", "4",
            "--model-code", AI_VIDEO_MODEL,
            "--prompt", prompt[:1200],
            "--aspect-ratio", "9:16",
            "--video-duration", str(ai_duration),
        ],
        label=f"ai-creation submit scene{scene.scene_id}",
    )

    ai_video_url = _run(
        _script("chanjing-ai-creation", "poll_task"),
        ["--unique-id", ai_unique_id],
        label=f"ai-creation poll scene{scene.scene_id}",
    )
    logger.info("  [AI] Scene %d 视频就绪: %s", scene.scene_id, ai_video_url[:60])

    # ffmpeg composite：AI 视频（CDN URL）+ 本地 WAV（无需 CDN 信号量处理音频）
    return _composite_video_audio(ai_video_url, wav_path)


def _render_mixed(plan: VideoPlan, script: ScriptResult,
                  storyboard: StoryboardResult) -> RenderResult:
    logger.info("[Mixed] 开始混合渲染（整篇 TTS → 切割 → 数字人+AI 并行）…")
    resolved = _resolve_figure(plan)
    audio_man_for_tts = resolved.audio_man_for_tts()

    with timed("full TTS", logger):
        full_wav = _generate_full_tts(script.full_script, audio_man_for_tts)

    with timed("split audio", logger):
        scene_wavs = _split_audio_by_scenes(full_wav, storyboard.scenes)

    def _render_scene(args: tuple[Scene, Path]) -> tuple[int, Path | None, list[str]]:
        scene, wav_path = args
        notes: list[str] = []
        try:
            if scene.use_avatar:
                clip = _render_dh_scene(resolved, scene, wav_path)
            else:
                clip = _render_ai_scene(scene, wav_path)
            logger.info("  Scene %d 完成 (%s)", scene.scene_id,
                        "DH" if scene.use_avatar else "AI")
            return scene.scene_id, clip, notes
        except Exception as exc:
            logger.warning("  Scene %d 失败，降级为数字人文本驱动: %s", scene.scene_id, exc)
            notes.append(f"scene_{scene.scene_id} render_failed: {exc}; dh_text_fallback")
            try:
                clip = _render_dh_scene(resolved, scene, None)
                logger.info("  Scene %d 降级成功 (DH text)", scene.scene_id)
                return scene.scene_id, clip, notes
            except Exception as exc2:
                logger.error("  Scene %d 完全失败: %s", scene.scene_id, exc2)
                notes.append(f"scene_{scene.scene_id} dh_fallback_failed: {exc2}")
                return scene.scene_id, None, notes

    clips_by_id: dict[int, Path | None] = {}
    scene_args = list(zip(storyboard.scenes, scene_wavs))
    degrade_log: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=SCENE_MAX_WORKERS) as pool:
        futures = {pool.submit(_render_scene, args): args[0] for args in scene_args}
        for future in concurrent.futures.as_completed(futures):
            scene_id, clip, notes = future.result()
            clips_by_id[scene_id] = clip
            degrade_log.extend(notes)

    ordered_clips: list[Path] = []
    scene_video_paths: list[str] = []
    for scene in storyboard.scenes:
        clip = clips_by_id.get(scene.scene_id)
        if clip:
            ordered_clips.append(clip)
            scene_video_paths.append(str(clip))
        else:
            scene_video_paths.append("")

    if not ordered_clips:
        raise RuntimeError("所有镜头渲染均失败")

    logger.info("[Mixed] 合并 %d 个片段…", len(ordered_clips))
    with timed("ffmpeg concat", logger):
        final_path = _concat_clips(ordered_clips)

    full_wav.unlink(missing_ok=True)
    for wav in scene_wavs:
        wav.unlink(missing_ok=True)
    for clip in ordered_clips:
        if clip != final_path:
            clip.unlink(missing_ok=True)

    logger.info("[Mixed] 完成: %s", final_path)
    return RenderResult(
        video_file=str(final_path),
        scene_video_urls=scene_video_paths,
        render_path="mixed_dh_ai",
        degrade_log=degrade_log,
    )


def _render_all_dh(plan: VideoPlan, script: ScriptResult,
                   storyboard: StoryboardResult) -> RenderResult:
    logger.info("[AllDH] 全数字人并行渲染（降级模式，文本驱动）…")
    resolved = _resolve_figure(plan)

    def _render_one(scene: Scene) -> tuple[int, Path | None]:
        try:
            clip = _render_dh_scene(resolved, scene, None)
            return scene.scene_id, clip
        except Exception as exc:
            logger.warning("  Scene %d 失败（跳过）: %s", scene.scene_id, exc)
            return scene.scene_id, None

    clips_by_id: dict[int, Path | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=SCENE_MAX_WORKERS) as pool:
        for scene_id, clip in pool.map(_render_one, storyboard.scenes):
            clips_by_id[scene_id] = clip

    ordered_clips = [clips_by_id[s.scene_id] for s in storyboard.scenes
                     if clips_by_id.get(s.scene_id)]
    scene_video_paths = [str(clips_by_id.get(s.scene_id) or "") for s in storyboard.scenes]

    if not ordered_clips:
        raise RuntimeError("所有镜头渲染均失败")

    with timed("ffmpeg concat (all-DH)", logger):
        final_path = _concat_clips(ordered_clips)

    for clip in ordered_clips:
        if clip != final_path:
            clip.unlink(missing_ok=True)

    return RenderResult(
        video_file=str(final_path),
        scene_video_urls=scene_video_paths,
        render_path="all_dh",
        degrade_log=["mixed_render_failed; used all_dh fallback"],
    )


def render_video(plan: VideoPlan, script: ScriptResult,
                 storyboard: StoryboardResult) -> RenderResult:
    if os.environ.get("STUB_MODE") == "1":
        return _stub_render(plan, storyboard)

    try:
        with timed("mixed render", logger):
            return _render_mixed(plan, script, storyboard)
    except Exception as exc:
        logger.warning("混合渲染失败，降级为全数字人: %s", exc)
        with timed("all-DH fallback", logger):
            return _render_all_dh(plan, script, storyboard)
