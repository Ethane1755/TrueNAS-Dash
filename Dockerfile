# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . .

# Create a directory for logs to ensure it exists
RUN mkdir -p logs

# Environment variable to ensure output is sent directly to terminal (avoids buffering)
ENV PYTHONUNBUFFERED=1

# Expose the port the app runs on
EXPOSE 5003

# Run app.py when the container launches
CMD ["python", "app.py"]
