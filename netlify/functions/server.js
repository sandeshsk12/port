const { spawn } = require('child_process');
const http = require('http');
const { URL } = require('url');
const fetch = require('node-fetch');

let streamlitProcess = null;

const startStreamlit = () => {
  if (streamlitProcess) return Promise.resolve();

  return new Promise((resolve, reject) => {
    console.log('Starting Streamlit server...');
    
    streamlitProcess = spawn('streamlit', [
      'run',
      'streamlit_app.py',
      '--server.port=8501',
      '--server.headless=true',
      '--server.enableCORS=false',
      '--server.enableXsrfProtection=false',
      '--server.runOnSave=false'
    ], {
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        STREAMLIT_SERVER_HEADLESS: 'true',
        STREAMLIT_SERVER_ENABLE_CORS: 'false',
      },
      stdio: ['pipe', 'pipe', 'pipe']
    });

    streamlitProcess.stdout.on('data', (data) => {
      console.log(`[Streamlit] ${data}`);
      if (data.toString().includes('You can now view your Streamlit app')) {
        console.log('Streamlit server started');
        resolve();
      }
    });

    streamlitProcess.stderr.on('data', (data) => {
      console.error(`[Streamlit Error] ${data}`);
    });

    streamlitProcess.on('error', (error) => {
      console.error('Failed to start Streamlit:', error);
      reject(error);
    });

    streamlitProcess.on('close', (code) => {
      console.log(`Streamlit process exited with code ${code}`);
      streamlitProcess = null;
    });
  });
};

const proxyRequest = async (event) => {
  const url = new URL(`http://localhost:8501${event.path}${event.rawQuery ? `?${event.rawQuery}` : ''}`);
  
  try {
    const response = await fetch(url.toString(), {
      method: event.httpMethod,
      headers: {
        ...event.headers,
        host: 'localhost:8501',
        'x-forwarded-for': event.headers['x-forwarded-for'] || '',
        'x-forwarded-proto': event.headers['x-forwarded-proto'] || 'http'
      },
      body: event.body ? Buffer.from(event.body, event.isBase64Encoded ? 'base64' : 'utf8') : undefined,
      redirect: 'manual'
    });

    const headers = {};
    response.headers.forEach((value, key) => {
      if (key.toLowerCase() !== 'content-encoding') {
        headers[key] = value;
      }
    });

    const isBinary = headers['content-type'] && !headers['content-type'].includes('text/');
    const responseBody = isBinary 
      ? (await response.buffer()).toString('base64')
      : await response.text();

    return {
      statusCode: response.status,
      headers,
      body: responseBody,
      isBase64Encoded: isBinary
    };
  } catch (error) {
    console.error('Proxy error:', error);
    return {
      statusCode: 500,
      body: JSON.stringify({ error: 'Internal Server Error', details: error.message }),
      headers: { 'Content-Type': 'application/json' }
    };
  }
};

exports.handler = async (event, context) => {
  try {
    // Only handle GET requests
    if (event.httpMethod !== 'GET') {
      return { statusCode: 405, body: 'Method Not Allowed' };
    }

    // Start Streamlit if not already running
    await startStreamlit();

    // Wait a moment for Streamlit to be ready
    await new Promise(resolve => setTimeout(resolve, 2000));

    // Proxy the request
    return await proxyRequest(event);
  } catch (error) {
    console.error('Handler error:', error);
    return {
      statusCode: 500,
      body: JSON.stringify({ error: 'Internal Server Error', details: error.message }),
      headers: { 'Content-Type': 'application/json' }
    };
  }
};
