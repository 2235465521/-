@echo off

chcp 65001 >nul

cd /d "%~dp0frontend"



where npm >nul 2>&1

if errorlevel 1 (

    echo [错误] 未找到 npm，请先安装 Node.js 并重新打开命令行。

    echo 下载: https://nodejs.org/

    pause

    exit /b 1

)



if not exist "node_modules" (

    echo [提示] 首次运行，正在安装前端依赖...

    call npm install

    if errorlevel 1 (

        echo [错误] npm install 失败

        pause

        exit /b 1

    )

)



echo.

echo 正在启动前端 http://127.0.0.1:5173

echo 请保持本窗口不要关闭。后端需另开 food-backend 窗口（8080）。

echo.

call npm run dev

pause

