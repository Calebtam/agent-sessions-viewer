# Agent Sessions Viewer

[English](README.md) | 中文

一个轻量级的 Web 查看器，用于浏览和搜索以 JSONL 格式导出的 Codex Agent 会话日志。

## 功能特性

- 浏览指定会话目录下的所有会话
- 按日期分组展示会话概览
- 查看每个会话的聊天式详细内容
- 支持在会话标题、文件名、预览问题、用户提问、助手回复和推理内容中搜索
- 在不修改原始文件的前提下，为会话设置展示名称
- 支持深色/浅色主题切换

## 项目结构

- backend/app.py：Flask API 服务与会话接口
- backend/parser.py：解析并格式化会话数据的逻辑
- frontend/index.html：单页前端界面
- session_metadata.json：会话的自定义展示名称

## 快速开始

1. 安装依赖

   ```bash
   pip install flask
   ```

2. 启动后端服务

   ```bash
   cd backend
   python3 app.py
   ```

   服务默认运行在 http://127.0.0.1:9000。

3. 打开前端页面

   ```bash
   xdg-open frontend/index.html
   ```

   如果浏览器对本地文件访问有限制，也可以直接访问后端首页：http://127.0.0.1:9000/。

## 配置说明

后端默认读取以下目录中的会话文件：

```bash
~/.codex/sessions
```

你也可以通过以下方式指定其他目录：

```bash
cd backend
python3 app.py --session_dir /path/to/your/sessions
```

## 说明

- 会话文件需要是配置目录下的 JSONL 文件。
- 查看器会使用 session_metadata.json 中保存的元数据，为会话提供自定义显示名称。
