# Usa una imagen base con Python
FROM python:3.9

# Establecer el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar los archivos de la aplicación al contenedor
COPY . .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Descargar modelos de Sentence Transformers para evitar descargas repetidas
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Definir la variable de entorno para Flask
ENV FLASK_APP=app.py

# Exponer el puerto correcto
EXPOSE 5001

# Comando para ejecutar la aplicación
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=5001"]
