FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend-vue/package.json ./
RUN npm install
COPY frontend-vue ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download en_core_web_sm
COPY . .
COPY --from=frontend /frontend/dist ./frontend-vue/dist

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
