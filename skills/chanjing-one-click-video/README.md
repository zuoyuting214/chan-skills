# chanjing-one-click-video

> 用户输入选题 → 自动生成「数字人口播 + AI 生成画面」混合短视频

本 skill 是 [chan-skills](https://github.com/chanjing-ai/chan-skills) 的一部分，与其他蝉镜工具共享同一套凭证配置，安装 chan-skills 即可直接使用，无需额外设置。

---

## 在 OpenClaw 中使用（推荐）

### 第一步：安装 chan-skills

```bash
git clone https://github.com/chanjing-ai/chan-skills.git
```

然后在 OpenClaw 中注册该 skill：

```bash
openclaw skill install /path/to/chan-skills/skills/chanjing-one-click-video
```

### 第二步：配置蝉镜凭证

如果你已经在用其他蝉镜 skill（`chanjing-tts`、`chanjing-video-compose` 等），凭证已配置，直接跳过。

否则运行引导配置：

```bash
python /path/to/chan-skills/skills/chanjing-credentials-guard/scripts/chanjing-config \
  --ak 你的app_id --sk 你的secret_key
```

或手动写入：

```bash
mkdir -p ~/.chanjing
echo '{"app_id":"你的app_id","secret_key":"你的secret_key"}' > ~/.chanjing/credentials.json
```

### 第三步：直接对话触发

安装后，在 OpenClaw 对话框里用自然语言说：

```
帮我做一个关于"为什么年轻人开始重视睡眠管理"的60秒抖音视频
```

```
根据这个选题生成一个短视频：家装公司怎么用短视频获客，平台微信视频号
```

```
帮我一键做成片，话题是呼吁减少使用一次性筷子，30秒
```

AI 会自动完成：规划 → 文案 → 分镜 → 渲染 → 输出视频文件路径。大约 8-12 分钟出片。

### 验证安装

```bash
python /path/to/chan-skills/skills/chanjing-one-click-video/scripts/check_deps.py
```

---

## 快速开始（命令行直接运行）

### 1. 配置凭证

```bash
# 蝉镜 AK/SK（写入 ~/.chanjing/credentials.json）
# 联系蝉镜获取 AK/SK，或运行 chanjing-credentials-guard

# 小鹿 DeerAPI Key（用于 LLM 生成文案/分镜）
export DEERAPI_API_KEY="sk-..."

# chan-skills 仓库路径（渲染必填）
export CHAN_SKILLS_DIR="/path/to/chan-skills"
```

### 2. 运行（Stub 模式，不调用真实 API）

```bash
cd chanjing-one-click-video
STUB_MODE=1 python scripts/run_workflow.py --topic "为什么现在很多老板开始重视 AI agent"
```

### 3. 运行（真实模式）

```bash
python scripts/run_workflow.py \
  --topic "家装公司怎么用短视频获客" \
  --industry "家装" \
  --platform douyin \
  --duration 60 \
  --output result.json
```

---

## 目录结构

```
chanjing-one-click-video/
├── SKILL.md                    # OpenClaw skill 定义（触发条件、参数、说明）
├── README.md                   # 本文件
├── examples/
│   ├── example_input_1.json    # AI/企业服务选题示例
│   ├── example_input_2.json    # 家装行业选题示例
│   ├── example_input_3.json    # 家庭教育选题示例
│   └── example_output_1.json   # 完整输出示例
├── scripts/
│   ├── run_workflow.py         # 主入口：完整流程编排
│   ├── schemas.py              # 数据结构定义
│   ├── planners.py             # 模块 B：视频规划生成
│   ├── copywriter.py           # 模块 C：口播文案生成
│   ├── storyboard.py           # 模块 D：分镜脚本生成（混合分配）
│   ├── render.py               # 模块 E：渲染编排（混合 DH + AI 视频）
│   ├── _auth.py                # 蝉镜鉴权
│   ├── _llm.py                 # DeerAPI LLM 客户端
│   └── utils.py                # 日志、计时工具
├── templates/
│   ├── plan_prompt.md          # 视频规划 LLM 提示词
│   ├── script_prompt.md        # 文案生成 LLM 提示词
│   ├── storyboard_prompt.md    # 分镜生成 LLM 提示词（混合类型指令）
│   └── rewrite_hook_prompt.md  # 开场白优化提示词
└── tests/
    ├── test_plan_generation.py
    ├── test_script_generation.py
    ├── test_storyboard_generation.py
    └── test_end_to_end_stub.py
```

---

## 核心流程

```
用户输入选题
    ↓
[A] 输入标准化（补全默认值，验证选题是否有效）
    ↓
[B] 生成 video_plan（LLM：受众、角度、分镜数、语气）
    ↓
[C] 生成 script（LLM：标题、hook、全文、CTA）
    ↓
[D] 生成 storyboard（LLM：混合分配镜头类型）
    │   奇数段 → use_avatar=true（数字人口播）
    │   偶数段 → use_avatar=false（AI 生成画面）
    │   第 1 段和最后 1 段 → 强制数字人
    ↓
[E] 并行渲染所有镜头
    │   DH 镜头 → chanjing-video-compose（公共数字人 + TTS）
    │   AI 镜头 → chanjing-ai-creation（文生视频）
    │             + chanjing-tts（配音）
    │             → ffmpeg composite
    ↓
[F] ffmpeg concat → 最终 mp4（本地文件）
    ↓
输出统一 JSON + 视频文件路径
```

---

## 配置说明

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEERAPI_API_KEY` | 小鹿 DeerAPI Key | 必填 |
| `DEERAPI_BASE_URL` | 小鹿 API Base URL | `https://api.deerapi.com` |
| `LLM_MODEL` | LLM 模型 | `claude-sonnet-4-6` |
| `CHAN_SKILLS_DIR` | chan-skills 仓库根目录 | 必填（渲染） |
| `CHANJING_API_BASE` | 蝉镜 API Base URL | `https://open-api.chanjing.cc` |
| `CHANJING_CONFIG_DIR` | 蝉镜凭证目录 | `~/.chanjing` |
| `CHANJING_AVATAR_GENDER` | 公共数字人性别偏好 | `Female` |
| `CHANJING_VOICE_ID` | TTS 音色 ID | `""` (使用数字人默认音色) |
| `AI_VIDEO_MODEL` | AI 视频生成模型 | `Doubao-Seedance-1.0-pro` |
| `DEFAULT_PLATFORM` | 默认目标平台 | `douyin` |
| `DEFAULT_DURATION` | 默认视频时长（秒） | `60` |
| `DEFAULT_STYLE` | 默认视频风格 | `观点型口播` |
| `STUB_MODE` | 测试模式 | `0` |
| `LOG_LEVEL` | 日志级别 | `INFO` |

---

## 渲染说明

### 渲染架构：整篇 TTS → 按镜头切割 → 混合渲染

```
整篇文案 → chanjing-tts（一次调用）→ full_audio.wav
                        ↓
              按各镜头文字比例切割
                  ↙           ↘
         DH 镜头 WAV        AI 镜头 WAV
              ↓                  ↓
  upload → video-compose    ai-creation 视频
  （音频驱动，唇型精准）     + ffmpeg overlay
                  ↘           ↙
                  ffmpeg concat → mp4
```

B-roll 只做音频 overlay，不走 avatar 驱动——AI 生成的画面不会被错误地驱动嘴型。

### 镜头类型分配

| 镜头位置 | 类型 | 说明 |
|---------|------|------|
| 第 1 段 | 数字人（DH） | 开场必须数字人，建立信任感 |
| 最后 1 段 | 数字人（DH） | CTA 必须数字人，直接号召 |
| 中间奇数段 | 数字人（DH） | 观点输出、情绪表达 |
| 中间偶数段 | AI 画面 | 举例说明、场景描述，防视觉疲劳 |

### 耗时参考（5 段 60s 视频）

| 阶段 | 耗时 |
|------|------|
| LLM（规划+文案+分镜） | ~36s |
| 整篇 TTS + 切割 | ~15s |
| 云端并行生成（DH + AI） | ~2min |
| CDN 串行下载 + ffmpeg | ~5-10min |
| **总计** | **~8-12min** |

> CDN 下载使用串行模式（`CDN_MAX_CONCURRENT=1`），避免 Chanjing CDN 并发限流导致超时。

### 降级策略

- AI 画面镜头失败 → 自动降级为数字人，保证有视频输出
- 所有 DH 镜头失败 → 进入 all_dh 降级路径，顺序渲染
- `render_path` 字段记录实际使用的路径：`mixed_dh_ai` / `all_dh` / `stub`

---

## 示例

### 示例 1：AI 企业服务类

```bash
python scripts/run_workflow.py --topic "为什么现在很多老板开始重视 AI agent" \
  --industry "AI/企业服务" --duration 60
```

输出关键字段：
```json
{
  "status": "success",
  "script_result": {
    "title": "老板为啥突然迷上AI agent",
    "hook": "你有没有发现，身边越来越多的老板，开始不动声色地研究AI agent了？"
  },
  "render_result": {
    "video_file": "/tmp/output.mp4",
    "render_path": "mixed_dh_ai"
  }
}
```

### 示例 2：家装行业

```bash
python scripts/run_workflow.py --input examples/example_input_2.json
```

---

## 运行测试

```bash
# 全部测试（stub 模式，无需真实 API）
python -m unittest discover -s tests -v

# 单独运行 E2E 测试
STUB_MODE=1 python -m unittest tests/test_end_to_end_stub.py -v
```

---

## 错误排查

| 错误信息 | 原因 | 解决方法 |
|----------|------|----------|
| `输入过于模糊` | 选题太短或太笼统 | 提供更明确的选题（≥5字）|
| `CHAN_SKILLS_DIR 未设置` | 未设置环境变量 | `export CHAN_SKILLS_DIR=/path/to/chan-skills` |
| `蝉镜凭证未配置` | 未设置 AK/SK | 检查 `~/.chanjing/credentials.json` |
| `文案生成失败` | DEERAPI_API_KEY 未设置 | `export DEERAPI_API_KEY=sk-...` |
| `没有可用的公共数字人形象` | 账户无公共数字人权限 | 联系蝉镜开通 |
| `视频时长只能在[5,10]秒范围内` | AI 视频模型限制 | 已内置处理（duration 自动夹到 5-10s）|

---

## 已知限制

- 最终视频为本地 mp4 文件，暂不自动上传至 CDN（可手动上传）
- AI 画面视频单段 ≤10s，由 ffmpeg loop 补足较长镜头的视频内容
- CDN 下载为串行以避免限流，5 段视频约 5-10 分钟

---

## 与 Chanjing Claw 的集成

- `run_workflow.py` 接受 JSON 输入，输出标准 JSON
- `WorkflowResult` 可直接在聊天界面展示
- 支持通过 `--input` 参数接入自动化流水线
