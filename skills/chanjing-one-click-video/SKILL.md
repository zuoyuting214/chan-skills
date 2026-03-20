---
name: chanjing-one-click-video
description: 用户输入一个选题，自动生成完整短视频成片（文案、分镜、数字人口播 + AI 画面混剪）。适用于「一键成片」「根据选题做视频」等场景。
---

# chanjing-one-click-video

## 做什么

选题 → 本地生成 `video_plan`、口播全文、分镜 → **整篇一次 TTS** → 按分镜切音频 → 数字人镜头走 `chanjing-video-compose`（音频驱动），AI 镜头走 `chanjing-ai-creation` 文生视频并与切段 WAV 合成 → ffmpeg 拼接为本地 mp4。

**真值来源**：`scripts/run_workflow.py`（编排）与 `scripts/render.py`（渲染）。本文只写触发条件、前置、参数与调用方式，不重复脚本内步骤细节。

---

## 何时用 / 何时不用

**用**：一键成片、把话题做成口播短视频、要「生成视频」而不只是文案。

**不用**：只要文案/标题、运营策略、未明确要视频、或编辑已有成片。

---

## 前置

1. 先跑 `chanjing-credentials-guard`，`~/.chanjing/credentials.json` 含 `app_id`、`secret_key`。
2. 渲染必填：`export CHAN_SKILLS_DIR="/path/to/chan-skills"`（chan-skills 仓库根目录）。
3. 规划/文案/分镜为本地逻辑，**无需**外部 LLM API key。

---

## 环境变量（摘要）

| 类别 | 变量 |
|------|------|
| 路径 | `CHAN_SKILLS_DIR`（必填，渲染） |
| 数字人 | `CHANJING_AVATAR_GENDER`、`CHANJING_VOICE_ID`、`CHANJING_AVATAR_ID` 或 `CHANJING_PERSON_ID`、`CHANJING_FIGURE_TYPE`、`CHANJING_FIGURE_SOURCE`（`common` / `customised` / `auto`） |
| AI 画面 | `AI_VIDEO_MODEL`（默认 `Doubao-Seedance-1.0-pro`）；另有 `AI_IMAGE_MODEL`、`AI_VIDEO_I2V_MODEL` 等见各蝉镜 skill |
| 默认输入 | `DEFAULT_PLATFORM`、`DEFAULT_DURATION`、`DEFAULT_STYLE` |
| 调试 | `STUB_MODE=1` 不调真实 API；`LOG_LEVEL` |

指定 `avatar_id` / 环境里的 person id 时，会先对照 `list_figures`；`create_task` / `poll_task` 失败会**同一整段 TTS 下**依次换列表中其它形象重试。

---

## 硬性约束（与脚本一致）

1. **先定稿再渲染**：确认 plan / 全文 / 分镜后再开渲染，中途不改方向。  
2. **整篇一次 TTS**，再按比例切段；禁止按镜头单独 TTS。  
3. **混合分镜**：首尾优先数字人；中间奇数偏数字人、偶数偏 AI 画面（脚本内实现）。  
4. AI 镜头仅 overlay 切段音频，**不走** avatar 唇形驱动。  
5. 云端可并行提交；**CDN 下载串行**，降 429。  
6. 失败只在**当前步骤**降级/重试，不回滚已完成步骤。

---

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| `topic` | 是 | 明确选题，建议 ≥5 字 |
| `industry` | 否 | 行业 |
| `platform` | 否 | `douyin` / `shipinhao` / `xiaohongshu`，默认 `douyin` |
| `style` | 否 | 默认 `观点型口播` |
| `duration_sec` | 否 | 30 / 60 / 90，默认 60 |
| `use_avatar` | 否 | 默认 true |
| `strict_validation` | 否 | 默认 true；模糊选题可失败 |
| `allow_auto_expand_topic` | 否 | 默认 false |
| `max_retry_per_step` | 否 | 渲染步重试，默认 1 |

---

## 输出 JSON（结构）

`status`: `success` | `partial` | `failed`；含 `video_plan`、`script_result`（title / hook / full_script / cta）、`storyboard_result.scenes[]`（scene_id、duration_sec、voiceover、subtitle、visual_prompt、use_avatar、image_prompt、i2v_prompt）、`render_result`（`video_file`、`scene_video_urls`、`render_path`、`degrade_log`）、`error`、`debug.steps` / `total_sec`。渲染失败时仍尽量返回已生成的文案与分镜。

---

## 命令行

```bash
export CHAN_SKILLS_DIR="/path/to/chan-skills"

python scripts/run_workflow.py --topic "为什么现在很多老板开始重视 AI agent"

python scripts/run_workflow.py \
  --topic "家装公司怎么用短视频获客" --industry "家装" \
  --platform douyin --duration 60 --output result.json

python scripts/run_workflow.py --input examples/example_input_1.json

STUB_MODE=1 python scripts/run_workflow.py --topic "测试选题足够长用于校验"

# 与 JSON 字段对应
python scripts/run_workflow.py --topic "选题足够长" --no-strict-validation
python scripts/run_workflow.py --topic "模糊" --allow-expand-topic
python scripts/run_workflow.py --topic "选题足够长" --max-retry 2
```

自然语言触发示例：`根据选题「家装公司怎么用短视频获客」生成 60 秒抖音口播视频` → 读本文并执行 `run_workflow.py`，回传文案、分镜与本地视频路径。

---

## 依赖的其它 Skills

| Skill | 作用 |
|-------|------|
| `chanjing-credentials-guard` | 鉴权（前置） |
| `chanjing-video-compose` | 数字人 + 音频驱动合成 |
| `chanjing-tts` | 整篇口播转音频 |
| `chanjing-ai-creation` | AI 画面（文生视频等） |

---

## 验收要点

凭证与 `CHAN_SKILLS_DIR` 就绪 → 输入校验通过 → 产出 plan / 全文 / 分镜 → 整篇 TTS 与切段 → 混合渲染与本地 mp4 → 返回 JSON（含 `status`、`render_result`、`debug`）。

---

## 限制

本地 mp4，不自动上传；AI 单段时长受模型限制（脚本内夹到 5–10s，过长用 loop 补）；分镜段数通常随 plan 为 4–6 段。
