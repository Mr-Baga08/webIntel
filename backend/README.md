# 🧠 WebIntel - Web Intelligence Platform

A scalable, modular, full-stack web intelligence platform with dashboard UI, real-time scraping control, multi-level crawler, and full metadata extraction — built completely from free and open-source tools.

![WebIntel Dashboard](backend/static/screenshot.png)

## 🌟 Features

- **Web Scraping**: Extract clean content from web pages with Playwright and newspaper3k
- **Multi-level Crawler**: Recursive crawling with configurable depth and domain filtering
- **Real-time Controls**: Pause, resume, and abort scraping jobs mid-execution
- **Metadata Extraction**: Extract article content, authors, dates, and more
- **Vector Search**: Semantic search using Sentence-BERT and FAISS
- **REST API**: Full API access with rate limiting
- **Dashboard UI**: Clean, responsive interface with Jinja2 templates and optional React frontend
- **YAML Configuration**: Advanced crawl configurations through YAML
- **LLM Integration**: Structure extracted data with LLM parsing (optional)

## 🛡️ High-Level Architecture

```plaintext
┌────────────────────────────┐
│        Frontend UI         │ ← Jinja2 / React Dashboard
└────────────┬───────────────┘
             ↓
┌────────────────────────────┐
│ Flask App (app.py)         │ ← Entry point + Routes
│ - Receives search queries  │
│ - Sends control commands   │
│ - Serves dashboard views   │
└────────────┬───────────────┘
             ↓
┌────────────────────────────┐
│ Scheduler (APScheduler)     │ ← Job runner
└────────────┬───────────────┘
             ↓
┌────────────────────────────┐
│ Scraper Workers (Playwright)│
│ - Multi-level crawler       │
│ - Metadata extraction       │
└────────────┬───────────────┘
             ↓
┌────────────────────────────┐
│ NLP/Ranker Module           │ ← Sentence-BERT, Relevance scoring
└────────────┬───────────────┘
             ↓
┌────────────────────────────┐
│ Vector DB / Vector Store    │ ← FAISS or SQLite + embeddings
└────────────┬───────────────┘
             ↓
┌────────────────────────────┐
│ SQLite/PostgreSQL DB        │
│ - ScrapeRuns, Pages         │
│ - FTS5/Vector Search (opt)  │
└────────────┬───────────────┘
             ↓
┌────────────────────────────┐
│ REST API Layer              │ ← Flask Blueprint or FastAPI (optional)
└────────────────────────────┘
```

## 🚀 Getting Started

### Prerequisites

- Python 3.9+
- Node.js 14+ (for React frontend)
- Playwright
- SQLite or PostgreSQL

### Installation

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/webintel.git
   cd webintel
   ```

2. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Install Playwright browsers:
   ```
   playwright install chromium
   ```

4. Initialize the database:
   ```
   python -m backend.db.init_db
   ```

5. (Optional) Install and build React frontend:
   ```
   cd frontend
   npm install
   npm run build
   ```

### Running the Application

1. Start the Flask server:
   ```
   flask --app backend.app run
   ```

2. Access the dashboard at `http://localhost:5000`

### Docker Deployment

Build and run using Docker:

```
docker build -t webintel .
docker run -p 5000:5000 webintel
```

## 📋 Usage

### Basic Search

1. Enter a search query in the dashboard
2. Select crawl depth (0-3)
3. Click "Start Search"
4. Monitor progress and view results in real-time

### Advanced YAML Configuration

For advanced crawling, use the YAML configuration option:

```yaml
query: "Web Intelligence Platform"
start_urls:
  - https://example.com/page1
  - https://example.com/page2
allowed_domains:
  - example.com
max_depth: 2
max_pages: 50
follow_external_links: false
wait_time: 1.0
css_selectors:
  content: article
  title: h1
  description: meta[name="description"]
```

### API Endpoints

Full API documentation is available at `/api/docs`

Key endpoints:
- `POST /api/runs` - Start a new scrape job
- `GET /api/runs/{id}` - Get scrape run details
- `POST /api/runs/{id}/pause` - Pause a running job
- `POST /api/runs/{id}/resume` - Resume a paused job
- `POST /api/runs/{id}/stop` - Stop a job
- `GET /api/runs/{id}/pages` - Get pages from a scrape run
- `GET /api/pages/{id}` - Get page details
- `POST /api/vector-search` - Perform semantic search

## 🔧 Configuration

Environment variables:
- `DATABASE_URL`: Database connection string (default: SQLite)
- `SECRET_KEY`: Flask session secret key
- `PORT`: Web server port (default: 5000)

## 📚 Project Structure

```
webintel/
├── backend/                    # All backend logic 
│   ├── app.py                  # Flask entry point
│   ├── models.py               # SQLAlchemy models
│   ├── scheduler.py            # Background job management
│   ├── db/                     # DB config + migrations
│   ├── scraper/                # Crawler logic
│   ├── search/                 # Query handling and ranking
│   ├── api/                    # REST API
│   ├── templates/              # Jinja2 HTML views
│   ├── static/                 # JS, CSS, icons
│   └── tests/                  # Test modules
├── frontend/                   # React UI (optional)
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker configuration
└── README.md                   # This documentation
```

## 🧪 Testing

Run tests with pytest:

```
pytest backend/tests/
```

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

- [Playwright](https://playwright.dev/) for browser automation
- [Sentence-Transformers](https://www.sbert.net/) for semantic search
- [newspaper3k](https://newspaper.readthedocs.io/) for content extraction
- [FAISS](https://github.com/facebookresearch/faiss) for vector search