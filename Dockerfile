FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# Drake の pip wheel が必要とする実行時ライブラリ
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip wget ca-certificates \
        libegl1 libgl1 libglib2.0-0 libsm6 libx11-6 libxext6 libxt6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

ARG DRAKE_VERSION=1.58.0
RUN pip install "drake==${DRAKE_VERSION}"

# lbm_eval_models (約 820MB) を GitHub Release から取得して展開する
ARG MODELS_WHL_URL=https://github.com/ToyotaResearchInstitute/lbm_eval/releases/download/1.1.0/lbm_eval_models-1.1.0-py3-none-any.whl
RUN wget -nv -O /tmp/lbm_eval_models-1.1.0-py3-none-any.whl "${MODELS_WHL_URL}" \
    && pip install --no-deps /tmp/lbm_eval_models-1.1.0-py3-none-any.whl \
    && rm /tmp/lbm_eval_models-1.1.0-py3-none-any.whl

RUN useradd --create-home viewer
USER viewer
WORKDIR /app

# ステーション構成が参照する drake_models (Panda アームなど) をビルド時に取得しておく
RUN python3 -c "from pydrake.multibody.parsing import PackageMap; print(PackageMap().GetPath('drake_models'))"

COPY --chown=viewer:viewer app.py /app/app.py
COPY --chown=viewer:viewer static /app/static

EXPOSE 8080 7000
CMD ["python3", "/app/app.py", "serve"]
