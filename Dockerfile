FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    gnupg \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install Node.js (for frontend build)
RUN curl -sL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps chromium

# Install development frontend dependencies (if using React)
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install

# Copy application code
COPY . .

# Build frontend (if using React)
RUN cd frontend && npm run build

# Initialize database
RUN python -m backend.db.init_db

# Expose port
EXPOSE 5000

# Set environment variables
ENV FLASK_APP=backend.app
ENV FLASK_ENV=production
ENV DATABASE_URL=sqlite:///webintel.db

# Run the application
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0"]