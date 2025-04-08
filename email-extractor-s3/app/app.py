import os
import boto3
import logging
import base64
import platform
from flask import Flask, jsonify, request, Blueprint
from botocore.exceptions import ClientError
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app with path prefix
app = Flask(__name__)
bp = Blueprint('email_extractor', __name__, url_prefix='/api')

# Initialize AWS clients
s3_client = boto3.client('s3')
bedrock_runtime = boto3.client('bedrock-runtime')

# Configuration
BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'business-card-email-extractor')
S3_MOUNT_PATH = os.environ.get('S3_MOUNT_PATH', '/mnt/s3')
MODEL_ID = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"


def extract_emails_from_image(image_path):
    """
    Extract email addresses from business card images using Claude 3.5 Sonnet model.
    
    Args:
        image_path (str): Path to the image file
    
    Returns:
        list: List of extracted email addresses
    """
    try:
        # Read the image file
        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
        
        # System message
        system_message = [{
            "text": "You are an expert at extracting email addresses from business cards."
        }]
        
        # User message with image
        user_message = {
            "role": "user",
            "content": [
                {
                    "image": {
                        "format": "jpeg",
                        "source": {
                            "bytes": image_data
                        }
                    }
                },
                {
                    "text": """
                    Task: Extract email addresses from this business card image.
                    
                    Instructions:
                    1. Identify all email addresses visible in the business card.
                    2. Return only the email addresses in a JSON array format.
                    3. If no email addresses are found, return an empty array.
                    
                    Example response: ["john@example.com"] or [] if none found.
                    """
                }
            ]
        }
        
        # Inference config
        inference_config = {
            "maxTokens": 4000,
            "temperature": 0
        }
        
        # Call the converse API
        response = bedrock_runtime.converse(
            modelId=MODEL_ID,
            messages=[user_message],
            system=system_message,
            inferenceConfig=inference_config
        )
        
        # Parse the response
        response_text = response["output"]["message"]["content"][0]["text"]
        
        # Extract the JSON array from the response
        try:
            # Try to parse the entire response as JSON
            emails_json = json.loads(response_text)
            if isinstance(emails_json, list):
                return emails_json
        except json.JSONDecodeError:
            # If the entire response isn't valid JSON, try to extract just the array part
            import re
            array_match = re.search(r'\[\s*"[^"]*"(?:\s*,\s*"[^"]*")*\s*\]', response_text)
            if array_match:
                return json.loads(array_match.group(0))
        
        # If all else fails, use regex to find email patterns
        import re
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        emails = re.findall(email_pattern, response_text)
        return emails
    
    except Exception as e:
        logger.error(f"Error extracting emails from image: {str(e)}")
        return []



# Blueprint routes
@bp.route('/', methods=['GET'])
def index():
    """Root endpoint"""
    arch = platform.machine()
    return jsonify({
        "status": "Email Extractor API is running",
        "architecture": arch,
        "endpoints": [
            "/extract",
            "/list-images"
        ]
    })

@bp.route('/extract', methods=['POST'])
def extract_email():
    """
    Extract emails from an image in the S3 bucket
    
    Request JSON:
    {
        "image_key": "path/to/image.jpg"
    }
    
    Returns:
    {
        "emails": ["email1@example.com", "email2@example.com"],
        "image_key": "path/to/image.jpg",
        "status": "success"
    }
    """
    try:
        # Get image key from request
        request_data = request.get_json()
        if not request_data or 'image_key' not in request_data:
            return jsonify({"error": "Missing image_key parameter"}), 400
        
        image_key = request_data['image_key']
        
        # Get full path to the image file in the mounted S3 path
        image_path = os.path.join(S3_MOUNT_PATH, image_key)
        
        # Check if file exists
        if not os.path.exists(image_path):
            return jsonify({
                "error": f"Image not found: {image_key}",
                "mount_path": S3_MOUNT_PATH,
                "full_path": image_path
            }), 404
        
        # Extract emails from the image
        emails = extract_emails_from_image(image_path)
        
        # Return the extracted emails
        return jsonify({
            "emails": emails,
            "image_key": image_key,
            "status": "success"
        })
    
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return jsonify({"error": str(e), "status": "error"}), 500


@bp.route('/list-images', methods=['GET'])
def list_images():
    """
    List available images in the S3 bucket
    
    Query parameters:
    - prefix (optional): Filter images by prefix
    
    Returns:
    {
        "images": ["path/to/image1.jpg", "path/to/image2.jpg"],
        "status": "success"
    }
    """
    try:
        # Get prefix from query parameters
        prefix = request.args.get('prefix', '')
        
        # List files in mounted S3 path
        images = []
        
        for root, _, files in os.walk(os.path.join(S3_MOUNT_PATH, prefix)):
            for file in files:
                # Check if file is an image
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp')):
                    # Get relative path from mount point
                    rel_path = os.path.relpath(os.path.join(root, file), S3_MOUNT_PATH)
                    images.append(rel_path)
        
        return jsonify({
            "images": images,
            "status": "success"
        })
    
    except Exception as e:
        logger.error(f"Error listing images: {str(e)}")
        return jsonify({"error": str(e), "status": "error"}), 500


@bp.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

# Register blueprint
app.register_blueprint(bp)


if __name__ == '__main__':
    # Check if the S3 mount is available
    if not os.path.exists(S3_MOUNT_PATH):
        logger.error(f"S3 mount path not found: {S3_MOUNT_PATH}")
    else:
        logger.info(f"S3 mount path found: {S3_MOUNT_PATH}")
    
    # Start the Flask app
    app.run(host='0.0.0.0', port=5000)
