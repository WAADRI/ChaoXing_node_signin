curl -o "other-signin-node.py" "https://api.waadri.top/ChaoXing/download/other-signin-node.py"

IMAGE_NAME="ccr.ccs.tencentyun.com/misaka-public/waadri-sign-node"

echo "构建arm64"
docker buildx build \
    --builder default \
    --platform linux/arm64 \
    -t $IMAGE_NAME:arm64 \
    --push \
    .

echo "构建amd64"
docker buildx build \
    --builder default \
    --platform linux/amd64 \
    -t $IMAGE_NAME:amd64 \
    --push \
    .
docker tag $IMAGE_NAME:amd64 $IMAGE_NAME:latest
docker push $IMAGE_NAME:latest