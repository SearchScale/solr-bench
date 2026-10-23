#!/usr/bin/env bash
# Builds libluxir_lucene.so inside Luxir's dev container (GCC 16 + vcpkg dependencies).
# Usage: luxir-bench/build-native.sh /path/to/solr-luxir
#   where solr-luxir holds the luxir and luxir-lucene checkouts side by side.
# Output: <root>/luxir/build/lux4j-release/bin/libluxir_lucene.so (+ libgomp.so.1 next to it)
set -euo pipefail

root=$(cd "${1:?usage: $0 /path/to/solr-luxir}" && pwd)
image=${LUXIR_DEV_IMAGE:-luxir-dev:normal-deps}
shared_cache=${LUXIR_CACHE_DIR:-$HOME/.cache/luxir}
home_dir="$root/luxir/build/container-cache/$(id -u)/home"
mkdir -p "$home_dir" "$shared_cache/container-ccache"

if ! docker image inspect "$image" > /dev/null 2>&1; then
  echo "Building the Luxir dev image $image (this takes a while the first time)"
  (cd "$root/luxir" && DOCKER_BUILDKIT=1 docker build -f .devcontainer/Dockerfile \
    --target normal-dependencies -t "$image" --build-arg BUILD_JOBS="$(nproc)" .)
fi

# Container path, since the build runs inside the container
echo 'include(/workspace/luxir-lucene/native/lxl.cmake)' > "$root/luxir/LocalTargets.cmake"

docker run --rm --init --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$root/luxir,target=/workspace/luxir" \
  --mount "type=bind,source=$root/luxir-lucene,target=/workspace/luxir-lucene,readonly" \
  --mount "type=bind,source=$shared_cache,target=/luxir-cache" \
  --workdir /workspace/luxir \
  --env "HOME=/workspace/luxir/build/container-cache/$(id -u)/home" \
  --env LUXIR_CACHE_DIR=/luxir-cache \
  --env CCACHE_DIR=/luxir-cache/container-ccache \
  "$image" bash -c '
    set -euo pipefail
    # The container preset links GCC runtimes statically, but its libgomp.a is not PIC and
    # cannot go into a shared library. Keep libstdc++/libgcc static, link libgomp shared and
    # ship GCC 16 libgomp.so.1 next to the .so (a distro GCC one may be too old).
    cmake --preset container-release -B build/lux4j-release --fresh \
      -DLUXIR_JEMALLOC=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DLUXIR_LOCAL_TARGETS=ON \
      -DLUXIR_CPU_TARGET=native -DLUXIR_STATIC_RUNTIME=OFF \
      "-DCMAKE_SHARED_LINKER_FLAGS=-static-libstdc++ -static-libgcc" \
      "-DCMAKE_BUILD_RPATH=\$ORIGIN"
    cmake --build build/lux4j-release --target luxir_lucene
    cp -L "$(g++ -print-file-name=libgomp.so.1)" build/lux4j-release/bin/
  '

ldd "$root/luxir/build/lux4j-release/bin/libluxir_lucene.so"
ls -la "$root/luxir/build/lux4j-release/bin/libluxir_lucene.so"
