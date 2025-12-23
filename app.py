"""
AI Lead Prioritization System Backend - Fixed Data Extraction
"""

# Import libraries
import os
import json
import pandas as pd
import numpy as np
import re
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import io
from collections import defaultdict
import traceback
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# =============================================
# Configuration
# =============================================

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend

# File upload configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

# Create uploads directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Global data storage
processed_data = {
    'leads': [],
    'stats': {},
    'charts': {},
    'file_info': None,
    'is_processed': False
}

# AI Configuration
HF_API_KEY = os.environ.get("HF_API_KEY")
ai_client = None

# =============================================
# Helper Functions
# =============================================

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def read_data_file(filepath):
    """Read Excel or CSV file and extract lead data with proper column detection"""
    try:
        # Read the Excel file with header in row 1 (second row)
        df = pd.read_excel(filepath, header=1)
        
        print(f"📄 Loaded file with {len(df)} rows and {len(df.columns)} columns")
        print(f"📊 Columns: {list(df.columns)}")
        
        # Display first few rows for debugging
        print("First 3 rows:")
        print(df.head(3))
        
        # Process leads
        leads = []
        for idx, row in df.iterrows():
            try:
                # Get ID
                lead_id = str(row.get('ID', '')).strip()
                if pd.isna(lead_id) or lead_id == 'nan':
                    lead_id = f'LD{idx:04d}'
                
                # Get name
                first_name = str(row.get('Name', '')).strip()
                last_name = str(row.get('Last Name', '')).strip()
                
                if first_name and last_name:
                    full_name = f"{first_name} {last_name}"
                elif first_name:
                    full_name = first_name
                elif last_name:
                    full_name = last_name
                else:
                    full_name = f"Customer {idx+1}"
                
                # Get car details
                make = str(row.get('Make', '')).strip()
                model = str(row.get('Modell', '')).strip()
                
                if pd.isna(make) or make == 'nan':
                    make = 'Unknown'
                if pd.isna(model) or model == 'nan':
                    model = 'Unknown'
                
                # Get year
                year_value = row.get('Year', 0)
                if pd.isna(year_value):
                    year = 0
                else:
                    try:
                        year = int(float(year_value))
                    except:
                        year = 0
                
                # Get price estimation
                price_value = row.get('Price estimation', 0)
                if pd.isna(price_value):
                    price = 0
                else:
                    try:
                        price = float(price_value)
                    except:
                        price = 0
                
                # Get transcript
                transcript = str(row.get('Transcript', '')).strip()
                if pd.isna(transcript) or transcript == 'nan':
                    transcript = ''
                
                # Get call successful status
                success_value = row.get('Call successful', False)
                if pd.isna(success_value):
                    call_successful = False
                else:
                    if isinstance(success_value, bool):
                        call_successful = success_value
                    else:
                        success_str = str(success_value).strip().upper()
                        call_successful = success_str in ['TRUE', 'YES', 'JA', '1', 'SUCCESS']
                
                # Get notes/status
                notes = str(row.get('Status', '')).strip()
                
                lead = {
                    'id': lead_id,
                    'name': full_name,
                    'make': make,
                    'model': model,
                    'car': f"{make} {model}",
                    'year': year,
                    'priceEstimation': price,
                    'callSuccessful': call_successful,
                    'transcript': transcript,
                    'notes': notes,
                    'rawData': {
                        'rowIndex': idx,
                        'firstName': first_name,
                        'lastName': last_name,
                        'make': make,
                        'model': model,
                        'year': year,
                        'price': price,
                        'transcript': transcript[:100] if transcript else ''
                    }
                }
                leads.append(lead)
                
                print(f"✅ Processed lead {idx+1}: {lead['name']} | ID: {lead['id']} | Car: {lead['car']} | Year: {lead['year']} | Price: €{lead['priceEstimation']} | Call Successful: {lead['callSuccessful']}")
                
            except Exception as e:
                print(f"⚠️ Error processing row {idx}: {e}")
                traceback.print_exc()
                continue
        
        print(f"✅ Successfully loaded {len(leads)} leads")
        return leads
        
    except Exception as e:
        print(f"❌ Error reading data file: {e}")
        traceback.print_exc()
        raise

def get_default_insights():
    """Return default insights when AI analysis is not available"""
    return {
        "askingPrice": 0,
        "willingnessNegotiate": "unclear",
        "handoverDate": "unclear",
        "carCondition": "unclear",
        "numOwners": "unclear",
        "userSentiment": "neutral"
    }

def calculate_lead_score(insights, call_successful, year, price_estimation):
    """Calculate lead priority score based on insights"""
    if not call_successful:
        return 10  # Low score for unsuccessful calls
    
    score = 30  # Base score for successful call
    
    # Negotiation willingness
    negotiation_scores = {"high": 25, "medium": 15, "low": 5, "unclear": 0}
    score += negotiation_scores.get(insights.get("willingnessNegotiate", "unclear"), 0)
    
    # Handover date urgency
    handover_scores = {"immediate": 20, "1-2 weeks": 15, "2-4 weeks": 10, "flexible": 5, "unclear": 0}
    score += handover_scores.get(insights.get("handoverDate", "unclear"), 0)
    
    # Car condition
    condition_scores = {"excellent": 15, "good": 10, "fair": 5, "poor": 0, "unclear": 0}
    score += condition_scores.get(insights.get("carCondition", "unclear"), 0)
    
    # Sentiment
    sentiment_scores = {"positive": 10, "neutral": 5, "negative": 0}
    score += sentiment_scores.get(insights.get("userSentiment", "neutral"), 0)
    
    # Year factor (newer cars are better)
    if year > 2015:
        score += 10
    elif year > 2010:
        score += 5
    
    # Price estimation factor
    if price_estimation > 0:
        score += min(10, price_estimation / 1000)
    
    return min(100, max(0, int(score)))

def get_priority_level(score):
    """Get priority level based on score - using frontend terminology"""
    if score >= 70:
        return "hot"
    elif score >= 40:
        return "warm"
    else:
        return "cold"

def process_leads_data(leads):
    """Process all leads with AI analysis"""
    processed = []
    total_leads = len(leads)
    
    print(f"🚀 Starting processing for {total_leads} leads...")
    
    for i, lead in enumerate(leads):
        if i % 5 == 0 or i == total_leads - 1:
            print(f"   📊 Processing lead {i + 1}/{total_leads}: {lead.get('name', 'Unknown')}")
        
        if lead['callSuccessful'] and lead['transcript'] and len(lead['transcript'].strip()) > 20:
            try:
                insights = extract_insights_with_ai(lead['transcript'])
                print(f"   🤖 Extracted insights: {insights}")
                score = calculate_lead_score(
                    insights,
                    lead['callSuccessful'],
                    lead['year'],
                    lead['priceEstimation']
                )
                print(f"   📈 Calculated score: {score}")
            except Exception as e:
                print(f"⚠️ AI analysis failed for lead {i+1}: {e}")
                insights = get_default_insights()
                score = 10
        else:
            insights = get_default_insights()
            score = 10  # Default low score for unsuccessful calls or no transcript
        
        processed_lead = {
            **lead,
            'insights': insights,
            'priorityScore': score,
            'priorityLevel': get_priority_level(score),
            'processedAt': datetime.now().isoformat()
        }
        processed.append(processed_lead)
    
    # Sort by priority score (highest first)
    processed.sort(key=lambda x: x['priorityScore'], reverse=True)
    
    print(f"✅ Successfully processed {len(processed)} leads")
    print("📊 Top 3 leads:")
    for i, lead in enumerate(processed[:3]):
        print(f"   {i+1}. {lead['name']} - Score: {lead['priorityScore']} - Level: {lead['priorityLevel']}")
    
    return processed

def calculate_statistics(leads, is_processed=False):
    """Calculate statistics from processed leads"""
    if not leads:
        return get_empty_stats()
    
    total = len(leads)
    successful_calls = sum(1 for lead in leads if lead['callSuccessful'])
    
    # Only calculate priority distribution if leads have been processed
    if is_processed and leads and 'priorityLevel' in leads[0]:
        priority_counts = {
            'hot': sum(1 for lead in leads if lead['priorityLevel'] == 'hot'),
            'warm': sum(1 for lead in leads if lead['priorityLevel'] == 'warm'),
            'cold': sum(1 for lead in leads if lead['priorityLevel'] == 'cold')
        }
        
        # Calculate average score
        if leads and 'priorityScore' in leads[0]:
            scores = [lead['priorityScore'] for lead in leads]
            avg_score = np.mean(scores) if scores else 0
            min_score = min(scores) if scores else 0
            max_score = max(scores) if scores else 0
        else:
            avg_score = 0
            min_score = 0
            max_score = 0
            
        # Count immediate handover leads
        immediate_handover = 0
        for lead in leads:
            if lead.get('insights', {}).get('handoverDate') == 'immediate':
                immediate_handover += 1
    else:
        priority_counts = {'hot': 0, 'warm': 0, 'cold': 0}
        avg_score = 0
        min_score = 0
        max_score = 0
        immediate_handover = 0
    
    # Top 5 leads (sorted by priority score if processed, otherwise just first 5)
    if is_processed and leads and 'priorityScore' in leads[0]:
        # Leads are already sorted by priorityScore from process_leads_data
        top_leads = leads[:5] if len(leads) >= 5 else leads
    else:
        top_leads = leads[:5] if len(leads) >= 5 else leads
    
    # Car models distribution (top 5)
    make_counts = defaultdict(int)
    for lead in leads:
        make_counts[lead['make']] += 1
    
    top_makes = [{'make': make, 'count': count} for make, count in 
                 sorted(make_counts.items(), key=lambda x: x[1], reverse=True)[:5]]
    
    return {
        'totalLeads': total,
        'successfulCalls': successful_calls,
        'successRate': round((successful_calls / total * 100) if total > 0 else 0, 1),
        'averageScore': round(avg_score, 1),
        'hotLeads': priority_counts.get('hot', 0),
        'minScore': min_score,
        'maxScore': max_score,
        'immediateHandover': immediate_handover,
        'priorityDistribution': priority_counts,
        'topMakes': top_makes,
        'topLeads': top_leads,
        'processedAt': datetime.now().isoformat()
    }

def get_empty_stats():
    """Return empty statistics matching frontend expectations"""
    return {
        'totalLeads': 0,
        'successfulCalls': 0,
        'successRate': 0,
        'averageScore': 0,
        'hotLeads': 0,
        'minScore': 0,
        'maxScore': 0,
        'immediateHandover': 0,
        'priorityDistribution': {'hot': 0, 'warm': 0, 'cold': 0},
        'topMakes': [],
        'topLeads': [],
        'processedAt': datetime.now().isoformat()
    }

def generate_chart_data(leads, is_processed=False):
    """Generate chart data for visualization"""
    if not leads:
        return {
            'scoreDistribution': [],
            'priorityDistribution': [],
            'successRate': [],
            'topLeads': []
        }
    
    # Success rate (always available)
    successful = sum(1 for lead in leads if lead['callSuccessful'])
    unsuccessful = len(leads) - successful
    success_rate_data = [
        {'status': 'Successful', 'count': successful},
        {'status': 'Unsuccessful', 'count': unsuccessful}
    ]
    
    # Top leads for chart (formatted for frontend)
    top_leads_chart = []
    if is_processed and leads and 'priorityScore' in leads[0]:
        for lead in leads[:5]:  # Top 5 leads
            top_leads_chart.append({
                'name': lead['name'],
                'level': lead['priorityLevel'],
                'score': lead['priorityScore']
            })
    
    # Only generate score and priority distribution if leads have been processed
    if is_processed and leads and 'priorityScore' in leads[0]:
        # Score distribution (buckets)
        score_buckets = [0, 20, 40, 60, 80, 100]
        score_dist = [0] * (len(score_buckets) - 1)
        
        for lead in leads:
            score = lead['priorityScore']
            for i in range(len(score_buckets) - 1):
                if score_buckets[i] <= score < score_buckets[i + 1]:
                    score_dist[i] += 1
                    break
            if score == 100:
                score_dist[-1] += 1
        
        score_dist_data = [{'range': f'{score_buckets[i]}-{score_buckets[i+1]}', 'count': count} 
                          for i, count in enumerate(score_dist)]
        
        # Priority distribution
        priority_dist = {'hot': 0, 'warm': 0, 'cold': 0}
        for lead in leads:
            priority_dist[lead['priorityLevel']] += 1
        
        priority_dist_data = [{'level': level, 'count': count} 
                              for level, count in priority_dist.items()]
    else:
        score_dist_data = []
        priority_dist_data = []
    
    return {
        'scoreDistribution': score_dist_data,
        'priorityDistribution': priority_dist_data,
        'successRate': success_rate_data,
        'topLeads': top_leads_chart
    }

# =============================================
# AI Functions - Fixed to work without API key
# =============================================

def initialize_ai_client():
    """Initialize AI client with Hugging Face"""
    global ai_client, HF_API_KEY
    
    if not HF_API_KEY:
        print("⚠️ HF_API_KEY not found in .env file - using rule-based scoring only")
        return None
    
    try:
        # Try to use OpenAI-compatible endpoint
        from openai import OpenAI
        
        ai_client = OpenAI(
            base_url="https://api-inference.huggingface.co/v1/",
            api_key=HF_API_KEY
        )
        print("✅ Hugging Face Inference API client initialized successfully")
        return ai_client
    except ImportError:
        print("❌ OpenAI package not installed. Run: pip install openai>=1.0.0")
        return None
    except Exception as e:
        print(f"❌ Error initializing AI client: {e}")
        return None

def extract_insights_from_transcript_rules(transcript):
    """Extract insights using rule-based analysis when AI is not available"""
    insights = get_default_insights()
    
    if not transcript or len(transcript.strip()) < 20:
        return insights
    
    transcript_lower = transcript.lower()
    
    # Extract asking price
    price_patterns = [
        r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?:€|euro|eur)',
        r'(?:€|euro|eur)\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)',
        r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*tausend',
        r'zwischen\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*und\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)'
    ]
    
    for pattern in price_patterns:
        matches = re.findall(pattern, transcript_lower)
        if matches:
            try:
                if isinstance(matches[0], tuple):  # Range pattern
                    price_str = matches[0][0].replace(',', '').replace('.', '')
                    insights["askingPrice"] = float(price_str)
                else:
                    price_str = str(matches[0]).replace(',', '').replace('.', '')
                    insights["askingPrice"] = float(price_str)
                break
            except:
                pass
    
    # Determine negotiation willingness
    if any(word in transcript_lower for word in ['spielraum', 'runtergehen', 'verhandeln', 'verhandlungsbereit', 'ja,']):
        insights["willingnessNegotiate"] = "high"
    elif any(word in transcript_lower for word in ['vielleicht', 'möglich', 'eventuell']):
        insights["willingnessNegotiate"] = "medium"
    elif any(word in transcript_lower for word in ['fest', 'fix', 'unverhandelbar', 'nein']):
        insights["willingnessNegotiate"] = "low"
    
    # Determine handover date
    if any(word in transcript_lower for word in ['sofort', 'jetzt', 'heute', 'immediate', 'jederzeit', 'so bald wie möglich', 'bereit zum abholen']):
        insights["handoverDate"] = "immediate"
    elif any(word in transcript_lower for word in ['woche', '14 tage', 'zwei wochen', 'innerhalb von vierzehn tagen']):
        insights["handoverDate"] = "1-2 weeks"
    elif any(word in transcript_lower for word in ['monat', '4 wochen', 'drei monate', 'innerhalb der nächsten drei monaten']):
        insights["handoverDate"] = "2-4 weeks"
    elif any(word in transcript_lower for word in ['flexibel', 'egal', 'kein druck']):
        insights["handoverDate"] = "flexible"
    
    # Determine car condition
    if any(word in transcript_lower for word in ['exzellent', 'perfekt', 'wie neu', 'hundert prozent', 'sehr gut', 'wie neu']):
        insights["carCondition"] = "excellent"
    elif any(word in transcript_lower for word in ['gut', 'in ordnung']):
        insights["carCondition"] = "good"
    elif any(word in transcript_lower for word in ['okay', 'akzeptabel', 'gebrauchtsspuren']):
        insights["carCondition"] = "fair"
    elif any(word in transcript_lower for word in ['schaden', 'unfall', 'reparatur', 'schramme']):
        insights["carCondition"] = "poor"
    
    # Extract number of owners
    if 'erstbesitzer' in transcript_lower or 'ein besitzer' in transcript_lower or 'nur mich' in transcript_lower or 'einen' in transcript_lower:
        insights["numOwners"] = 1
    elif 'zwei besitzer' in transcript_lower:
        insights["numOwners"] = 2
    elif 'drei besitzer' in transcript_lower:
        insights["numOwners"] = 3
    
    # Determine user sentiment
    positive_words = ['danke', 'super', 'perfekt', 'gut', 'gerne', 'freut', 'ja', 'okay', 'in ordnung']
    negative_words = ['lügen', 'nein', 'nicht', 'kein', 'probleme', 'schlecht']
    
    pos_count = sum(1 for word in positive_words if word in transcript_lower)
    neg_count = sum(1 for word in negative_words if word in transcript_lower)
    
    if pos_count > neg_count:
        insights["userSentiment"] = "positive"
    elif neg_count > pos_count:
        insights["userSentiment"] = "negative"
    
    return insights

def extract_insights_with_ai(transcript):
    """Extract structured insights using AI or fallback to rules"""
    global ai_client, HF_API_KEY
    
    # First try AI if available
    if HF_API_KEY and ai_client:
        try:
            # Create prompt for German transcripts
            prompt = f"""
            Extrahiere Verkaufsinformationen aus diesem deutschen Autoverkaufsgespräch:
            {transcript[:500]}
            
            Gib die Antwort als JSON mit genau diesen Schlüsseln:
            {{
                "askingPrice": Zahl (0 wenn unbekannt),
                "willingnessNegotiate": "high", "medium", "low" oder "unclear",
                "handoverDate": "immediate", "1-2 weeks", "2-4 weeks", "flexible" oder "unclear",
                "carCondition": "excellent", "good", "fair", "poor" oder "unclear",
                "numOwners": Zahl oder "unclear",
                "userSentiment": "positive", "neutral" oder "negative"
            }}
            
            Wenn Informationen nicht erwähnt werden, verwende "unclear" oder 0.
            
            JSON:
            """
            
            response = ai_client.completions.create(
                model="gpt2",
                prompt=prompt,
                max_tokens=200,
                temperature=0.1
            )
            
            result_text = response.choices[0].text.strip()
            print(f"📄 AI Response: {result_text[:100]}...")
            
            # Try to extract JSON
            try:
                json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if json_match:
                    insights = json.loads(json_match.group())
                    
                    # Validate and fill missing keys
                    default_insights = get_default_insights()
                    for key in default_insights:
                        if key not in insights:
                            insights[key] = default_insights[key]
                    
                    print(f"✅ Successfully extracted insights with AI")
                    return insights
            except json.JSONDecodeError:
                print(f"⚠️ Could not parse JSON from AI response, using rules")
                
        except Exception as e:
            print(f"⚠️ AI analysis failed: {e}")
    
    # Fallback to rule-based analysis
    print("🔄 Using rule-based analysis")
    return extract_insights_from_transcript_rules(transcript)

# =============================================
# API Routes
# =============================================

@app.route('/')
def home():
    """Home endpoint - API information"""
    return jsonify({
        'name': 'AI Lead Prioritization API',
        'version': '6.0.0',
        'status': 'active',
        'ai_enabled': ai_client is not None,
        'endpoints': {
            'GET /api/health': 'Check API health',
            'POST /api/upload': 'Upload Excel/CSV file',
            'POST /api/process': 'Process leads',
            'GET /api/dashboard': 'Get dashboard data',
            'GET /api/leads': 'Get leads with filters',
            'GET /api/stats': 'Get statistics',
            'GET /api/export/excel': 'Export to Excel',
            'GET /api/test/ai': 'Test AI connection'
        }
    })

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Upload Excel/CSV file endpoint"""
    global processed_data
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed. Please upload Excel (.xlsx, .xls) or CSV files.'}), 400
    
    try:
        # Save file
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        print(f"📁 File saved: {filepath}")
        
        # Read and process file
        leads = read_data_file(filepath)
        
        # Store in global data
        processed_data['leads'] = leads
        processed_data['file_info'] = {
            'filename': filename,
            'uploadedAt': datetime.now().isoformat(),
            'leadCount': len(leads),
            'processed': False,
            'filepath': filepath
        }
        processed_data['is_processed'] = False
        
        # Calculate basic stats (without priorityLevel since leads aren't processed yet)
        stats = calculate_statistics(leads, is_processed=False)
        processed_data['stats'] = stats
        processed_data['charts'] = generate_chart_data(leads, is_processed=False)
        
        return jsonify({
            'success': True,
            'message': f'File uploaded successfully. {len(leads)} leads loaded.',
            'filename': filename,
            'leadCount': len(leads),
            'stats': stats,
            'sample': leads[:3] if len(leads) >= 3 else leads,
            'file_info': processed_data['file_info']
        })
        
    except ImportError as e:
        return jsonify({
            'error': f'Missing dependency: {str(e)}',
            'solution': 'Run: pip install openpyxl'
        }), 500
    except Exception as e:
        print(f"❌ Upload error: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Error processing file: {str(e)}'}), 500

@app.route('/api/process', methods=['POST'])
def process_leads():
    """Process leads with AI analysis"""
    global processed_data
    
    if not processed_data['leads']:
        return jsonify({'error': 'No data available. Please upload an Excel or CSV file first.'}), 400
    
    try:
        print("🚀 Starting lead processing...")
        
        # Process leads
        processed_leads = process_leads_data(processed_data['leads'])
        
        # Update processed data
        processed_data['leads'] = processed_leads
        processed_data['stats'] = calculate_statistics(processed_leads, is_processed=True)
        processed_data['charts'] = generate_chart_data(processed_leads, is_processed=True)
        processed_data['is_processed'] = True
        
        # Update file info
        if processed_data['file_info']:
            processed_data['file_info']['processedAt'] = datetime.now().isoformat()
            processed_data['file_info']['processed'] = True
            processed_data['file_info']['aiUsed'] = ai_client is not None
        
        return jsonify({
            'success': True,
            'message': f'Successfully processed {len(processed_leads)} leads.',
            'stats': processed_data['stats'],
            'sample': processed_leads[:3],
            'ai_enabled': ai_client is not None
        })
        
    except Exception as e:
        print(f"❌ Processing error: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Error processing leads: {str(e)}'}), 500

@app.route('/api/dashboard', methods=['GET'])
def get_dashboard():
    """Get complete dashboard data"""
    global processed_data
    
    if not processed_data['leads']:
        return jsonify({
            'empty': True,
            'message': 'No data available. Please upload a file first.'
        })
    
    return jsonify({
        'empty': False,
        'fileInfo': processed_data['file_info'],
        'stats': processed_data['stats'],
        'charts': processed_data['charts'],
        'leads': processed_data['leads'],  # Send all leads for the table
        'isProcessed': processed_data['is_processed'],
        'aiEnabled': ai_client is not None
    })

@app.route('/api/leads', methods=['GET'])
def get_leads():
    """Get leads with optional filtering"""
    global processed_data
    
    if not processed_data['leads']:
        return jsonify({'leads': []})
    
    # Get filter parameters
    priority = request.args.get('priorityLevel', '').lower()
    search = request.args.get('search', '').lower()
    min_score = int(request.args.get('minScore', 0))
    max_score = int(request.args.get('maxScore', 100))
    sort = request.args.get('sort', 'score')
    order = request.args.get('order', 'desc')
    limit = int(request.args.get('limit', 50))
    make = request.args.get('make', '').lower()
    
    # Filter leads
    filtered_leads = processed_data['leads']
    
    # Filter by priority (only if leads have been processed)
    if priority and priority in ['hot', 'warm', 'cold'] and processed_data['is_processed']:
        filtered_leads = [lead for lead in filtered_leads 
                         if lead.get('priorityLevel', '').lower() == priority]
    
    # Filter by make
    if make:
        filtered_leads = [lead for lead in filtered_leads 
                         if make in lead.get('make', '').lower()]
    
    # Filter by search
    if search:
        filtered_leads = [lead for lead in filtered_leads 
                         if search in lead.get('name', '').lower() or 
                         search in lead.get('car', '').lower() or 
                         search in lead.get('id', '').lower()]
    
    # Filter by score range (only if leads have been processed)
    if processed_data['is_processed']:
        filtered_leads = [lead for lead in filtered_leads 
                         if min_score <= lead.get('priorityScore', 0) <= max_score]
    
    # Sort (only if leads have been processed and have priorityScore)
    if processed_data['is_processed'] and sort == 'score':
        filtered_leads.sort(key=lambda x: x.get('priorityScore', 0), reverse=(order == 'desc'))
    elif sort == 'price':
        filtered_leads.sort(key=lambda x: x.get('priceEstimation', 0), reverse=(order == 'desc'))
    elif sort == 'year':
        filtered_leads.sort(key=lambda x: x.get('year', 0), reverse=(order == 'desc'))
    elif sort == 'name':
        filtered_leads.sort(key=lambda x: x.get('name', '').lower(), reverse=(order == 'desc'))
    
    # Apply limit
    filtered_leads = filtered_leads[:limit]
    
    return jsonify({'leads': filtered_leads})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get statistics"""
    global processed_data
    return jsonify(processed_data['stats'])

@app.route('/api/charts', methods=['GET'])
def get_charts():
    """Get chart data"""
    global processed_data
    return jsonify(processed_data['charts'])

@app.route('/api/export/excel', methods=['GET'])
def export_excel():
    """Export processed leads to Excel"""
    global processed_data
    
    if not processed_data['leads']:
        return jsonify({'error': 'No data available'}), 400
    
    try:
        # Prepare data for export
        export_data = []
        for lead in processed_data['leads']:
            insights = lead.get('insights', {})
            export_row = {
                'Lead ID': lead.get('id', ''),
                'Customer Name': lead.get('name', ''),
                'Car Make': lead.get('make', ''),
                'Car Model': lead.get('model', ''),
                'Year': lead.get('year', ''),
                'Call Successful': 'Yes' if lead.get('callSuccessful') else 'No',
                'Price Estimation': lead.get('priceEstimation', 0),
                'Transcript Preview': lead.get('transcript', '')[:200]
            }
            
            # Add processed fields if available
            if processed_data['is_processed']:
                export_row.update({
                    'Priority Score': lead.get('priorityScore', ''),
                    'Priority Level': lead.get('priorityLevel', ''),
                    'Asking Price': insights.get('askingPrice', 0),
                    'Negotiation Willingness': insights.get('willingnessNegotiate', 'unclear'),
                    'Handover Date': insights.get('handoverDate', 'unclear'),
                    'Car Condition': insights.get('carCondition', 'unclear'),
                    'Number of Owners': insights.get('numOwners', 'unclear'),
                    'Customer Sentiment': insights.get('userSentiment', 'neutral'),
                    'Processed At': lead.get('processedAt', '')
                })
            
            export_data.append(export_row)
        
        # Create DataFrame
        df = pd.DataFrame(export_data)
        
        # Create Excel file in memory
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Leads')
        
        output.seek(0)
        
        # Send file
        filename = f"processed_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"❌ Export error: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Error exporting data: {str(e)}'}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'ai_configured': ai_client is not None,
        'data_loaded': len(processed_data['leads']) > 0,
        'data_count': len(processed_data['leads']),
        'is_processed': processed_data['is_processed'],
        'file_info': processed_data['file_info']
    })

@app.route('/api/test/ai', methods=['GET'])
def test_ai():
    """Test AI connection"""
    global ai_client, HF_API_KEY
    
    if not HF_API_KEY:
        return jsonify({
            'success': False,
            'error': 'HF_API_KEY not found in .env file',
            'instructions': [
                '1. Get API key from https://huggingface.co/settings/tokens',
                '2. Create a .env file in project root with:',
                '   HF_API_KEY=your_key_here',
                '3. Restart the server'
            ],
            'current_mode': 'Using rule-based analysis (no AI)'
        }), 500
    
    if not ai_client:
        return jsonify({
            'success': False,
            'error': 'AI client not initialized',
            'hint': 'Make sure the openai package is installed: pip install openai',
            'current_mode': 'Using rule-based analysis'
        }), 500
    
    try:
        # Test with a simple model
        response = ai_client.completions.create(
            model="gpt2",
            prompt="Hello, test connection.",
            max_tokens=10
        )
        
        return jsonify({
            'success': True,
            'message': 'AI is working!',
            'response': response.choices[0].text.strip(),
            'model': 'gpt2',
            'provider': 'Hugging Face Inference API'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'hint': 'Make sure HF_API_KEY is valid and you have internet connection',
            'current_mode': 'Using rule-based analysis as fallback'
        }), 500

# =============================================
# Application Startup
# =============================================

if __name__ == '__main__':
    # Initialize AI client
    ai_client = initialize_ai_client()
    
    print("🚀" + "="*60)
    print("🚀 AI Lead Prioritization System - Enhanced Version")
    print("🚀 Supports both AI and rule-based analysis")
    print("🚀" + "="*60)
    print("📡 API Server: http://localhost:5000")
    print("📁 Upload folder:", os.path.abspath(UPLOAD_FOLDER))
    print("🤖 AI Status:", "✅ Configured" if ai_client else "❌ Not configured (using rules)")
    
    if not ai_client:
        print("💡 Optional: To enable AI features:")
        print("   1. Get API key from https://huggingface.co/settings/tokens")
        print("   2. Create a .env file with: HF_API_KEY=your_key_here")
        print("   3. Install required packages: pip install openai openpyxl")
        print("   4. Restart the application")
    else:
        print("🌐 AI Model: gpt2")
    
    print("📊 Current Mode:", "AI Analysis" if ai_client else "Rule-based Analysis")
    print("="*60)
    print("✅ API is ready to accept requests")
    print("   Upload files at: http://localhost:5000")
    print("   Dashboard: http://localhost:5000/api/dashboard")
    print("   Health check: http://localhost:5000/api/health")
    print("="*60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)