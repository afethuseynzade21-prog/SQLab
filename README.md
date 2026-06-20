# 🎓 AzərMentor — Şəxsi Öyrənmə Mentor AI

> **Hər kəs üçün şəxsi mentor — nə öyrənəcəyini, nə vaxt, hansı ardıcıllıqla.**

[![CI](https://github.com/azermentor/azermentor/actions/workflows/ci.yaml/badge.svg)](https://github.com/azermentor/azermentor/actions)
[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-green)](https://fastapi.tiangolo.com)
[![MLflow](https://img.shields.io/badge/MLflow-2.9-orange)](https://mlflow.org)

---

## 🎯 Nədir?

AzərMentor, istifadəçinin bacarıqlarını, hədəflərini və öyrənmə tempini analiz edərək **şəxsi öyrənmə yolu** təklif edən AI sistemidir.

**Dillər:** 🇦🇿 Azərbaycan | 🇬🇧 İngilis

---

## 🏗️ Arxitektura

```
İstifadəçi Profili
       ↓
   FastAPI
  ↙       ↘
Claude API   ML Model (LSTM/ANN)
  ↘       ↙
  Tövsiyə
       ↓
 React Dashboard
```

---

## 📁 Struktur

```
azermentor/
├── .github/workflows/    # CI/CD
│   ├── ci.yaml           # Test + Build
│   └── deploy.yaml       # Production deploy
├── configs/
│   └── config.yaml       # Konfiqurasiya
├── data/
│   ├── raw/              # Orijinal data
│   ├── processed/        # Hazır data
│   └── validation/       # Validasiya
├── src/
│   ├── data/
│   │   ├── ingestion.py      # Data yüklə
│   │   └── preprocessing.py  # Hazırla
│   ├── models/
│   │   ├── train.py          # MLflow training
│   │   └── architectures/    # ANN, LSTM
│   ├── pipelines/
│   │   └── training_pipeline.py
│   └── monitoring/
├── api/
│   ├── main.py           # FastAPI app
│   └── routes/
│       ├── mentor.py     # Tövsiyə endpoints
│       └── health.py     # Health check
├── docker/
│   └── Dockerfile
├── docker-compose.yaml
├── dvc.yaml              # Data pipeline
├── params.yaml           # Hyperparameters
└── requirements.txt
```

---

## 🚀 Başlat

### 1. Mühiti qur

```bash
git clone https://github.com/sən/azermentor
cd azermentor
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. API key əlavə et

```bash
cp .env.example .env
# .env faylında ANTHROPIC_API_KEY əlavə et
```

### 3. Docker ilə başlat

```bash
docker-compose up -d
```

### 4. API-ya daxil ol

```
FastAPI:  http://localhost:8000
Docs:     http://localhost:8000/docs
MLflow:   http://localhost:5000
Frontend: http://localhost:3000
```

---

## 🔌 API İstifadəsi

### Tövsiyə al

```bash
curl -X POST http://localhost:8000/api/v1/mentor/tövsiyə \
  -H "Content-Type: application/json" \
  -d '{
    "ad": "Əli",
    "sahə": "data_science",
    "səviyyə": "beginner",
    "hədəf": "iş tapmaq",
    "öyrənmə_saatı": 2.0,
    "dil": "az"
  }'
```

### Cavab

```json
{
  "növbəti_mövzu": "Python + Pandas əsasları",
  "izah": "Data science üçün əsas alətlər",
  "addımlar": [
    "1. Python sintaksisini öyrən",
    "2. Pandas ilə CSV oxu",
    "..."
  ],
  "həftəlik_plan": "Bazar ertəsi: Python...",
  "motivasiya": "Əli, sən doğru yoldasan!",
  "müddət": "2-3 həftə"
}
```

---

## 🧠 MLOps Pipeline

```bash
# Tam pipeline çalıştır
python -m src.pipelines.training_pipeline

# DVC ilə
dvc repro

# MLflow UI
mlflow ui
```

---

## 🔄 Project Flow

```
Code Push → CI (test + lint) → Data Check (DVC) →
Train Model → MLflow Track → Register →
Docker Build → Deploy → Monitor → Retrain
```

---

## 👥 Hədəf Auditoriya

| İstifadəçi | Ehtiyac |
|-----------|---------|
| 🎓 Tələbə | "Haradan başlayım?" |
| 💼 Karyera dəyişən | "Nə öyrənim?" |
| 👨‍💻 Developer | "Boşluğum haradadır?" |
| 📚 Öz-özünə öyrənən | "Ardıcıllıq nədir?" |

---

## 📊 Tech Stack

| Komponent | Texnologiya |
|-----------|------------|
| AI Mentor | Claude API (claude-opus-4-6) |
| ML Model | TensorFlow / LSTM |
| API | FastAPI |
| Tracking | MLflow |
| Data | DVC |
| Deploy | Docker + GitHub Actions |
| Frontend | React |

---

*Azərbaycan üçün, Azərbaycan dilində 🇦🇿*
