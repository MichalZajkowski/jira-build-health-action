FROM python:3.10-slim

WORKDIR /app

# Copy files
COPY requirements.txt .
COPY analyzer.py .
COPY entrypoint.sh .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Set entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
