# 前端说明

本目录是 **静态页面**（`index.html` + `css/` + `js/`），由 Flask 直接托管。

- **没有** Vite / React / Vue 工程依赖
- **不需要** `npm install` 才能跑业务（仅当部署脚本强制执行 `npm run build` 时，可用下方兼容脚本）

## 正确启动

在项目**根目录**启动后端即可，例如 Windows 双击 `启动ZKBZ.bat`，浏览器打开 http://127.0.0.1:5000/ 。

## 若流水线执行了 `npm run build`

```bash
cd frontend
npm run build
```

会运行空构建：把静态文件复制到 `frontend/dist/` 并成功退出，避免 `ENOENT: package.json`。  
应用仍应由 Flask 从 `frontend/`（或你配置的静态根）提供服务，而不是单独起 Node 静态站替代后端 API。
