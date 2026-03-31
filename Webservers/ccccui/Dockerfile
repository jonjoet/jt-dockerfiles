FROM chopchop:ATCC13032

RUN pip install --no-cache-dir streamlit

WORKDIR /app
COPY app.py .
COPY annotate_targets.sh .
RUN chmod +x annotate_targets.sh

EXPOSE 8501

ENTRYPOINT ["streamlit", "run", "app.py", \
    "--server.port=8501", \
    "--server.address=0.0.0.0", \
    "--browser.gatherUsageStats=false"]
