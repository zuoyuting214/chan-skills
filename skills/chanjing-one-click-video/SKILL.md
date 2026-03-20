---
name: chanjing-one-click-video
description: 用户输入一个选题，自动生成完整短视频成片（文案、分镜、数字人口播 + AI 生成画面混合剪辑、合成视频）。适用于"一键成片"、"根据选题做视频"等场景。
---

# chanjing-one-click-video

## 目的

将用户输入的选题（一句话话题）自动编排为完整的「数字人口播 + AI 生成画面」混合型短视频，包括：

1. 输入标准化（补全默认值，验证选题是否有效）
2. 生成 `video_plan`（视频规划：受众、角度、镜头数、语气）
3. 生成口播文案（标题、hook、全文、CTA）
4. 生成分镜脚本（混合分配：奇数段=数字人、偶数段=AI 画面）
5. 并行渲染所有镜头（DH 镜头用 video-compose，AI 镜头用 ai-creation + TTS）
6. ffmpeg 本地合成最终视频
7. 输出统一结构化结果 + 本地视频文件路径

---

## 何时触发

当用户表达以下意图时触发：

- "根据这个选题生成一个短视频"
- "帮我一键做成片"
- "把这个话题做成口播视频"
- "生成一个适合抖音的 60 秒视频"
- "我有个选题，帮我做成视频"
- "一键成片"

---

## 何时不触发

以下场景**不要**触发该 skill：

- 用户只是要一段文案（不需要视频）
- 用户只是要标题或选题列表
- 用户只是要运营分析或策略建议
- 用户没有明确要"生成视频"
- 用户要编辑已有视频

---

## 前置条件

本 skill 已内置在 [chan-skills](https://github.com/chanjing-ai/chan-skills) 仓库中，与其他 skill 共享同一套蝉镜凭证，无需额外安装。

**唯一必填项：** 蝉镜凭证（`~/.chanjing/credentials.json`），格式：

```json
{"app_id": "你的app_id", "secret_key": "你的secret_key"}
```

如尚未配置，运行 `chanjing-credentials-guard` 可引导完成配置。

**可选配置：**

```bash
export DEERAPI_API_KEY="sk-..."          # 独立调用 LLM 时使用（在 OpenClaw 等 AI 平台中不需要）
export CHANJING_AVATAR_GENDER="Female"   # 公共数字人性别偏好（Male/Female）
export CHANJING_VOICE_ID="..."           # 指定 TTS 音色 ID（留空自动选数字人默认音色）
export AI_VIDEO_MODEL="Doubao-Seedance-1.0-pro"  # AI 视频生成模型
export DEFAULT_PLATFORM="douyin"
export DEFAULT_DURATION="60"
export STUB_MODE="1"                     # 测试模式，不调用真实 API
```

---

## 输入参数

### 必填

| 参数 | 类型 | 说明 |
|------|------|------|
| `topic` | string | 视频选题，需要明确具体（不少于 5 个字）|

### 可选

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `industry` | string | `""` | 行业，如"家装"、"AI/企业服务" |
| `platform` | string | `"douyin"` | 目标平台：`douyin` / `shipinhao` / `xiaohongshu` |
| `style` | string | `"观点型口播"` | 视频风格：干货 / 观点 / 种草 / 口播 |
| `duration_sec` | int | `60` | 视频时长：30 / 60 / 90（秒）|
| `use_avatar` | bool | `true` | 是否使用数字人口播 |

---

## 输出结果

统一返回 JSON 结构：

```json
{
  "status": "success | partial | failed",
  "video_plan": { ... },
  "script_result": {
    "title": "视频标题",
    "hook": "开场钩子",
    "full_script": "完整口播文案",
    "cta": "结尾行动号召"
  },
  "storyboard_result": {
    "scenes": [
      {
        "scene_id": 1,
        "duration_sec": 10,
        "voiceover": "口播文本",
        "subtitle": "字幕文本",
        "visual_prompt": "画面描述",
        "use_avatar": true
      }
    ]
  },
  "render_result": {
    "video_file": "/tmp/output.mp4",
    "scene_video_urls": ["...", "..."],
    "render_path": "mixed_dh_ai | all_dh | stub"
  },
  "error": null,
  "debug": {
    "steps": { "plan_sec": 7, "script_sec": 13, "storyboard_sec": 16, "render_sec": 480 },
    "total_sec": 516
  }
}
```

即使渲染失败，也会尽可能返回已生成的文案和分镜（`status: "partial"`）。

---

## 执行方式

### 直接调用主脚本

```bash
# 基础用法
python scripts/run_workflow.py --topic "为什么现在很多老板开始重视 AI agent"

# 完整参数
python scripts/run_workflow.py \
  --topic "家装公司怎么用短视频获客" \
  --industry "家装" \
  --platform douyin \
  --style 干货 \
  --duration 60 \
  --output result.json

# 从 JSON 文件输入
python scripts/run_workflow.py --input examples/example_input_1.json

# Stub 模式（不调用真实 API，用于测试）
STUB_MODE=1 python scripts/run_workflow.py --topic "AI agent 如何改变企业运营"
```

### 在 Claude Code 中使用

```
请根据选题"家装公司怎么用短视频获客"生成一个 60 秒的抖音口播视频
```

Claude Code 会：
1. 读取本 SKILL.md
2. 调用 `scripts/run_workflow.py`
3. 展示生成的文案、分镜和本地视频文件路径

---

## 渲染路径说明

本 skill 采用「整篇一次性 TTS → 按镜头切割 → 数字人+AI 混合渲染」策略：

### 为什么用整篇 TTS

逐镜头 TTS 会在每个镜头边界处重置语调，导致语气断裂。整篇一次性 TTS 生成连贯自然的音频，再按各镜头口播文字的字符数比例切割为独立 WAV 段，分别交给各镜头使用。B-roll 只做音频 overlay，不经过 avatar 驱动，避免错误地驱动 AI 生成的画面。

| 镜头类型 | 分配规则 | 渲染方式 |
|---------|---------|---------|
| 数字人（DH） | 第 1 段、最后 1 段，以及奇数编号的中间段 | `chanjing-video-compose` 音频驱动（上传 WAV，唇型精准匹配） |
| AI 画面 | 偶数编号的中间段 | `chanjing-ai-creation`（文生视频）+ 本地 WAV 直接合成（不走 avatar） |

所有场景**并行提交**云端任务，CDN 下载阶段使用串行信号量（避免 Chanjing CDN 限流）。最终由 ffmpeg concat 合成本地 mp4。

**典型耗时（5 段 60s 视频）：**

| 阶段 | 耗时 |
|------|------|
| LLM（规划+文案+分镜） | ~36s |
| 云端并行生成（DH+AI） | ~2min |
| CDN 串行下载 + ffmpeg | ~5-10min |
| **总计** | **~8-12min** |

---

## 与其他蝉镜 Skills 的依赖关系

| Skill | 用途 | 必填 |
|-------|------|------|
| `chanjing-video-compose` | 公共数字人 + TTS 视频合成 | 是 |
| `chanjing-tts` | AI 画面镜头的独立配音 | 是 |
| `chanjing-ai-creation` | AI 视频生成（Doubao-Seedance） | 是 |
| `chanjing-credentials-guard` | 鉴权 | 是（前置） |

---

## 错误处理

- **输入过于模糊**：直接返回提示，不进入生成流程
- **文案/分镜生成失败**：返回已完成阶段 + 失败原因（`status: partial`）
- **AI 画面镜头失败**：自动降级为数字人（保证最终有视频输出）
- **渲染全部失败**：仍然返回文案和分镜，不丢失成果
- **鉴权失败**：提示用户检查 `~/.chanjing/credentials.json`

---

## 已知限制

1. 最终视频为**本地 mp4 文件**，暂不自动上传（CDN 上传接口待接入）
2. AI 画面视频时长受模型限制（5-10s），超长镜头由 ffmpeg loop 补足
3. CDN 下载为串行（避免限流），5 段视频约 5-10 分钟
4. 分镜数量由 video_plan 决定，通常 4-6 段
