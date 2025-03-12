#!/bin/bash

docker build -t 153-proj . && docker run --rm -ti -v $(pwd)/logs:/app/logs 153-proj