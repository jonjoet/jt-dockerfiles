FROM chopchop:ATCC13032

# Install Python 3 alongside existing Python 2.7 (needed by CHOPCHOP)
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir streamlit

WORKDIR /app
COPY app.py .
COPY annotate_targets.sh .
RUN chmod +x annotate_targets.sh

EXPOSE 8501

ENTRYPOINT ["python3", "-m", "streamlit", "run", "app.py", \
    "--server.port=8501", \
    "--server.address=0.0.0.0", \
    "--browser.gatherUsageStats=false"]
