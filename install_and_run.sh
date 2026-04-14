#!/bin/bash

# Check if Docker is installed
if ! [ -x "$(command -v docker)" ]; then
  echo 'Error: docker is not installed.' >&2
  echo 'Please install Docker and try again.' >&2
  exit 1
fi

# Check if docker compose is installed
if ! docker compose version > /dev/null 2>&1; then
  echo 'Error: docker compose is not installed or not available in the Docker CLI.' >&2
  echo 'Please ensure you have a recent version of Docker Desktop or Docker Engine with Compose V2.' >&2
  exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
  echo "Docker is not running."
  echo "Please start Docker and try again."
  exit 1
fi

echo "Building and running the Email Handler application..."
echo "This may take a few minutes..."

docker compose up --build
