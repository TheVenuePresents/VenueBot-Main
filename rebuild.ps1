# Remove existing container and image then rebuild
docker rm -f hostbot-container 2>$null
docker rmi hostbot 2>$null
docker build -t hostbot .
