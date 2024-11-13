#! /bin/bash

# 一键运行脚本
cd "$(dirname "$0")"
echo "—————— 一键部署脚本 ——————"

# 选择 Python 运行 / Docker 运行
echo "请选择运行方式"
echo "1. Python 运行（Python3.10+）"
echo "2. Docker 运行"
read -p "请选择运行方式 (1 or 2)：" num

if [ $num -eq 1 ]; then  

    # 检查 Python 版本
    PYHTON_VERSION=$(python3 --version 2>&1)
    echo "Python版本: $PYHTON_VERSION"

    # 下载代码 安装依赖
    curl -s -o "main.py" "https://api.waadri.top/ChaoXing/download/other-signin-node.py"
    pip install --user -r requirements.txt >/dev/null 2>&1
    pip install --user -r requirements.txt --break-system-packages >/dev/null 2>&1

    # 运行脚本
    python3 main.py

    # 输入节点名称
    read -p "请输入节点名称：" NODE_NAME
    sed -i "s/name: ''/name: '$NODE_NAME'/g" node_config.yaml

    # 再次运行脚本
    python3 main.py

elif [ $num -eq 2 ]; then

    # 尝试停止已运行的容器
    docker stop SignNode >/dev/null 2>&1 && docker rm SignNode >/dev/null 2>&1

    # 输入节点名称
    read -p "请输入节点名称：" NODE_NAME

    # 运行容器
    mkdir -p data
    docker run -it \
        --name=SignNode \
        -v $(pwd)/data:/data \
        --restart=always \
        -e NAME=$NODE_NAME \
        --dns=223.5.5.5 --dns=114.114.114.114 \
        ccr.ccs.tencentyun.com/misaka-public/waadri-sign-node
    
else
    echo "输入错误"
fi

