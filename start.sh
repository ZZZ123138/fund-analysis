#!/bin/bash
echo "============================="
echo "  基金分析系统 - 启动脚本"
echo "============================="

# 启动后端
echo "[1/2] 启动 FastAPI 后端 (端口 8000)..."
cd backend
pip install -r requirements.txt -q
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
cd ..

# 启动前端
echo "[2/2] 启动 Next.js 前端 (端口 3000)..."
cd frontend
npm install
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "============================="
echo "  服务已启动"
echo "  前端: http://localhost:3000"
echo "  后端: http://localhost:8000"
echo "  按 Ctrl+C 停止所有服务"
echo "============================="

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
