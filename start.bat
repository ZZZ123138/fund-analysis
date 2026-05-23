@echo off
chcp 65001 >nul
echo =============================
echo   基金分析系统 - 启动脚本
echo =============================

echo [1/2] 启动 FastAPI 后端 (端口 8000)...
cd /d %~dp0backend
pip install -r requirements.txt -q
start "FundAPI" python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
cd /d %~dp0

echo [2/2] 启动 Next.js 前端 (端口 3000)...
cd /d %~dp0frontend
call npm install
start "FundFrontend" npm run dev
cd /d %~dp0

echo.
echo =============================
echo   服务已启动
echo   前端: http://localhost:3000
echo   后端: http://localhost:8000
echo =============================
pause
