# Session 双栏对比功能

> 日期：2026-10-26  
> 范围：Codex、Copilot CLI、VS Code Chat 索引会话

## 使用方法

1. 点击顶栏 `Compare`。
2. 在左侧 Sessions 列表选择第一个会话，选中项显示编号 `1`。
3. 再选择一个不同会话，选中项显示编号 `2`。
4. Viewer 并行加载两个会话，并进入双栏对比页面。
5. 点击 `Exit compare` 或布局控件中的 `Exit` 退出。

同一个会话不能同时作为左右两侧；第二次点击已选会话不会重复加入。

## 布局映射

Compare 复用现有 `1 column / 2 columns / 3 columns` 控件：

| 布局 | 对比显示 |
|---|---|
| 1 column | 隐藏 Sessions 和两侧 Outline，显示 `正文 vs 正文` |
| 2 columns | 隐藏 Sessions，每侧显示 `Outline + 正文`，即 `2 vs 2` |
| 3 columns | 显示 Sessions，再显示两组 `Outline + 正文`，即 `1 + 2 vs 2` |

`Narrow / Medium / Full` 继续控制每一侧的正文宽度。布局、宽度、同步和退出按钮位于同一控件组。

## 同步滚动

完成两个会话加载后，控件组会出现 `Sync`：

- 默认关闭。
- 开启后按钮高亮。
- Viewer 预先比较两侧 turn 的标题、用户内容和助手内容，建立单调的内容对应关系；
  内容相似度不足时才使用顺序位置兜底。
- 滚动任意一侧时，另一侧进入对应 turn，并按当前 turn 内的相对进度连续滚动，
  而不是等跨过 turn 边界后再跳转。
- 两侧 Outline 同时高亮对应项，并自动滚动到可见区域。

无论是否开启 `Sync`，每一侧 Outline 都会独立跟随本侧正文、高亮当前项并保持可见。
开启 `Sync` 后才会驱动另一侧正文和 Outline。这样可以比较两个长度不同或中间有新增
turn 的会话，避免纯序号或整页滚动百分比逐渐偏离语义位置。

## 数据加载与边界

- 两个会话分别通过已有 Provider API 加载，不新增源文件写入。
- 单侧按 200 turns 分页读取，对比模式最多加载前 2000 turns。
- VS Code `index_only` 会话可以被选中，但会显示没有 transcript，不虚构正文。
- 退出后优先回到进入 Compare 前的详情；没有原详情时返回主页。

## 验证

```bash
sed -n '/^<script>$/,/^<\/script>$/p' frontend/index.html | sed '1d;$d' | node --check
python3 -m unittest discover -s tests -v
python3 scripts/verify_dual_providers.py
git diff --check
```

