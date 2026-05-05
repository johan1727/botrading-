FROM freqtradeorg/freqtrade:stable

# Copiar archivos del proyecto
COPY requirements.txt /freqtrade/
COPY user_data/ /freqtrade/user_data/
COPY config_dry_run.json /freqtrade/
COPY config.json /freqtrade/

# Instalar dependencias extra
RUN pip install -r requirements.txt --no-cache-dir

# Puerto para la WebUI
EXPOSE 8080

# Comando default: dry-run (cambiar a config.json para real)
CMD ["freqtrade", "trade", "--config", "config_dry_run.json", "--strategy", "GeminiStrategy", "--logfile", "user_data/logs/freqtrade.log"]
