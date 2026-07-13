# S14 德鲁伊本地装备顾问

本工作区保存三类可复用数据：

- `data/reference/`：带版本锁的赛季规则、固定 D2Core 构筑与计算公式；
- `data/user/current.json`：用户当前角色快照；每次更新自动保存到 `data/user/history/`；
- `data/user/candidates/`：尚未确认穿戴的截图装备，不会自动覆盖当前装备。

仓库内的 `skills/d4-druid-advisor/` 负责装备比较、最大单击、人物面板诊断和附魔建议工作流；Python工具只执行可复算的原子运算。

## 安装

```bash
scripts/setup-local.sh
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s "$(pwd)/skills/d4-druid-advisor" \
  "${CODEX_HOME:-$HOME/.codex}/skills/d4-druid-advisor"
```

OCR 在本地使用 RapidOCR/ONNX Runtime，不上传截图。虚拟环境保存在 `.venv/`，不会提交到 Git。

## 装备截图识别

```bash
scripts/d4advisor ocr /绝对路径/装备截图.png \
  --output data/user/candidates/ring.json
```

多张已装备截图优先使用批量模式；OCR 引擎只初始化一次，两个戒指按输入顺序映射为
`ring_1` 和 `ring_2`。先检查文字结果，不会因为剧情或绑定信息未解析而要求查看原图：

```bash
scripts/d4advisor ocr-batch /绝对路径/*.png \
  --output-dir data/user/candidates/batch \
  --require-complete
```

用户确认整批物品当前均已穿戴后，增加 `--equip` 可在所有关键字段通过校验后一次性、
原子写入人物档案并生成单份历史记录与快照：

```bash
scripts/d4advisor ocr-batch /绝对路径/*.png \
  --output-dir data/user/candidates/batch \
  --require-complete \
  --equip
```

输出保留每个字段的 OCR 置信度、原文、未解析文本、图片文件名和 SHA-256 指纹；不会写入包含用户目录或聊天软件账号的完整路径。只有用户确认装备已经穿戴后才更新角色：

```bash
scripts/d4advisor profile set-item \
  --slot ring_2 \
  --item-json data/user/candidates/ring.json \
  --source-image /绝对路径/装备截图.png
```

多张属性面板或秘术师列表使用通用批量文字模式，同一批只初始化一次 OCR 引擎：

```bash
scripts/d4advisor ocr-text-batch /绝对路径/面板*.png \
  --output-dir data/inbox/panel-ocr
```

护甲与抗性在当前规则中是递减收益评级。档案分别保存护甲评级、面板显示的减伤和 90%
减伤上限；不会再把 10,000 或其他固定护甲评级当成通用上限。

## 角色数据维护

```bash
scripts/d4advisor profile init
scripts/d4advisor profile show
scripts/d4advisor profile merge data/inbox/character-stats.json
scripts/d4advisor profile fingerprint
scripts/d4advisor profile render
```

`profile merge` 只覆盖允许的用户字段，拒绝改写构筑和版本等系统字段。每次写入使用原子替换、产生不可变历史快照，并重新生成可双击打开的 `data/user/snapshot.html`。

## 版本缓存

```bash
scripts/d4advisor version status
```

结果中的 `refresh_required` 为 `true` 时，后续伤害分析必须先核验官方补丁并更新 `version-lock.json`。工具不会在缓存过期后静默宣称旧规则仍然有效。

## 常用计算

```bash
# 盈月当空：33% 继续攻击，最多追加4次
scripts/d4advisor calc chain-attacks --probability 0.33 --max-extra 4

# 10000生命，两层20%和30%独立减伤
scripts/d4advisor calc ehp --life 10000 --reductions 0.2 0.3

# 单一伤害事件、装备A/B、人物面板审计与附魔候选排名
scripts/d4advisor calc damage-event --input data/inbox/damage-ledger.json
scripts/d4advisor calc compare --input data/inbox/comparison.json
scripts/d4advisor calc audit-panel --input data/inbox/panel-audit.json
scripts/d4advisor calc enchant --input data/inbox/enchantment-options.json \
  --output data/inbox/enchantment-result.json

# 可选：仅把附魔分析写入快照，不会改动当前穿戴与已确认附魔
scripts/d4advisor profile save-enchantment-analysis \
  --input data/inbox/enchantment-result.json
```

附魔计算输入必须包含刚由 `profile fingerprint` 产生的人物基线指纹。当本地版本数据未缓存
完整附魔池时，使用秘术师“可能属性”列表截图作为合法候选和 roll 范围的真值来源：

```bash
scripts/d4advisor ocr-text /绝对路径/可能属性列表.png \
  --output data/inbox/enchantment-affix-list.json
```

这些基础函数不会猜测未公开游戏数据。当前阶段支持版本化伤害、DPS、装备差值和 EHP；具体魔渊期望层数预测尚未实现。
