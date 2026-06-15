import json
import random
import string
import uuid
import boto3
from datetime import datetime

# DynamoDB setup
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
url_table = dynamodb.Table('url-shortener')
analytics_table = dynamodb.Table('url-analytics')


def generate_short_code(length=6):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=length))


def cors_headers():
    return {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
    }


def lambda_handler(event, context):

    print("EVENT:", json.dumps(event))

    http_method = (
        event.get('httpMethod')
        or event.get('requestContext', {})
        .get('http', {})
        .get('method', 'GET')
    )

    raw_path = event.get('rawPath', '')

    print("HTTP METHOD:", http_method)
    print("RAW PATH:", raw_path)

    # ==================================================
    # OPTIONS  →  CORS preflight (browser sends this first)
    # ==================================================
    if http_method == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': cors_headers(),
            'body': ''
        }

    # ==================================================
    # GET /urls  →  return all shortened URLs
    # ==================================================
    if http_method == 'GET' and raw_path.endswith('/urls'):
        try:
            response = url_table.scan()
            items = response.get('Items', [])

            # Sort newest first
            items.sort(
                key=lambda x: x.get('created_at', ''),
                reverse=True
            )

            return {
                'statusCode': 200,
                'headers': cors_headers(),
                'body': json.dumps({
                    'urls': items,
                    'total': len(items)
                }, default=str)
            }

        except Exception as e:
            print("Scan error:", str(e))
            return {
                'statusCode': 500,
                'headers': cors_headers(),
                'body': json.dumps({'error': 'Failed to fetch URLs'})
            }

    # ==================================================
    # POST /shorten  →  create and save a short URL
    # ==================================================
    if http_method == 'POST':

        body = json.loads(event.get('body', '{}'))
        long_url = body.get('url', '')

        if not long_url:
            return {
                'statusCode': 400,
                'headers': cors_headers(),
                'body': json.dumps({'error': 'Please provide a URL'})
            }

        if not long_url.startswith(('http://', 'https://')):
            return {
                'statusCode': 400,
                'headers': cors_headers(),
                'body': json.dumps({'error': 'URL must start with http:// or https://'})
            }

        # Generate unique short code
        short_code = generate_short_code()
        while True:
            response = url_table.get_item(Key={'short_code': short_code})
            if 'Item' not in response:
                break
            short_code = generate_short_code()

        # Save to DynamoDB
        url_table.put_item(Item={
            'short_code': short_code,
            'long_url': long_url,
            'created_at': datetime.utcnow().isoformat(),
            'click_count': 0
        })

        print(f"Created short URL: {short_code}")

        return {
            'statusCode': 200,
            'headers': cors_headers(),
            'body': json.dumps({
                'message': 'URL shortened successfully!',
                'short_code': short_code,
                'short_url': f'https://uaywpq8og7.execute-api.ap-south-1.amazonaws.com/prod/{short_code}',
                'long_url': long_url
            })
        }

    # ==================================================
    # GET /{shortCode}  →  redirect to original URL
    # ==================================================
    elif http_method == 'GET':

        path_params = event.get('pathParameters') or {}
        short_code = path_params.get('shortCode', '')

        print("SHORT CODE:", short_code)

        if not short_code:
            return {
                'statusCode': 200,
                'headers': cors_headers(),
                'body': json.dumps({'message': 'URL Shortener is running!'})
            }

        # Fetch from DynamoDB
        response = url_table.get_item(Key={'short_code': short_code})
        item = response.get('Item')

        if not item:
            return {
                'statusCode': 404,
                'headers': cors_headers(),
                'body': json.dumps({'error': 'Short URL not found'})
            }

        # Update click count
        try:
            url_table.update_item(
                Key={'short_code': short_code},
                UpdateExpression='ADD click_count :inc',
                ExpressionAttributeValues={':inc': 1}
            )
            print("Click count updated")
        except Exception as e:
            print("Click count update error:", str(e))

        # Save analytics record
        try:
            headers = event.get('headers', {}) or {}
            analytics_table.put_item(Item={
                'click_id': str(uuid.uuid4()),
                'short_code': short_code,
                'timestamp': datetime.utcnow().isoformat(),
                'ip_address': headers.get('X-Forwarded-For', 'Unknown'),
                'user_agent': headers.get('User-Agent', 'Unknown'),
                'referer': headers.get('Referer', 'Direct')
            })
            print("Analytics saved successfully")
        except Exception as e:
            print("Analytics save error:", str(e))

        # Redirect
        return {
            'statusCode': 301,
            'headers': {
                'Location': item['long_url'],
                'Access-Control-Allow-Origin': '*'
            },
            'body': ''
        }

    # ==================================================
    # METHOD NOT ALLOWED
    # ==================================================
    return {
        'statusCode': 405,
        'headers': cors_headers(),
        'body': json.dumps({'error': 'Method not allowed'})
    }