# S14 德鲁伊本地装备顾问

本工作区保存三类可复用数据：

- `data/reference/`：带版本锁的赛季规则、固定 D2Core 构筑与计算公式；
- `data/user/current.json`：用户当前角色快照；每次更新自动保存到 `data/user/history/`；
- `data/user/candidates/`：尚未确认穿戴的截图装备，不会自动覆盖当前装备。

## 安装

```bash
scripts/setup-local.sh
```

OCR 在本地使用 RapidOCR/ONNX Runtime，不上传截图。虚拟环境保存在 `.venv/`，不会提交到 Git。

## 装备截图识别

```bash
scripts/d4advisor ocr /绝对路径/装备截图.png \
  --output data/user/candidates/ring.json
```

输出保留每个字段的 OCR 置信度、原文、未解析文本、图片文件名和 SHA-256 指纹；不会写入包含用户目录或聊天软件账号的完整路径。只有用户确认装备已经穿戴后才更新角色：

```bash
scripts/d4advisor profile set-item \
  --slot ring_2 \
  --item-json data/user/candidates/ring.json \
  --source-image /绝对路径/装备截图.png
```

## 角色数据维护

```bash
scripts/d4advisor profile init
scripts/d4advisor profile show
scripts/d4advisor profile merge data/inbox/character-stats.json
```

`profile merge` 只覆盖提交的字段，已有装备和其他人物数据保持不变。每次写入使用原子替换并产生不可变历史快照。

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
```

这些基础函数不会猜测未公开游戏数据。完整伤害、DPS和魔渊层数计算会读取版本锁、固定构筑、用户实装与后续校准数据。
