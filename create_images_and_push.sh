#!/bin/bash

# set -x

# Define Docker Hub username
DOCKER_USERNAME="avekarpov"

# Define a list of images and their tags
# Format: "image_name1:tag1 directory1, image_name2:tag2 directory2, ..."
# Example: "myapp:latest ./myapp, backend:v1.0 ./backend"
DOCKERFILES="Dockerfile.gateway Dockerfile.flight Dockerfile.ticket Dockerfile.bonus Dockerfile.stats"

# Convert string to array
IFS=', ' read -r -a array <<< "$DOCKERFILES"

# Loop through the array and process each image
for element in "${array[@]}"
do
    # Split each element into image:tag and directory
    IFS='.' read -r -a parts <<< "$element"
    IMAGE_NAME="${parts[1]}"

    # Step 1: Build the Docker image
    echo "Building Docker image ticketservice-$IMAGE_NAME"
    docker build -q -f "$element" -t $DOCKER_USERNAME/ticketservice-$IMAGE_NAME .
    if [ $? -ne 0 ]; then
        echo "Docker build failed for ticketservice-$IMAGE_NAME"
        exit 1
    fi

    # Step 2: Push the Docker image to Docker Hub
    echo "Pushing Docker image $DOCKER_USERNAME/ticketservice-$IMAGE_NAME to Docker Hub..."
    docker push -q $DOCKER_USERNAME/ticketservice-$IMAGE_NAME
    if [ $? -ne 0 ]; then
        echo "Docker push failed for $DOCKER_USERNAME/ticketservice-$IMAGE_NAME"
        exit 1
    fi

    echo "Docker image $DOCKER_USERNAME/$IMAGE_NAME pushed successfully to Docker Hub"
done

echo "All Docker images pushed successfully to Docker Hub"