/**
 * Legal Document Extraction & Analysis Google Sheets App
 * Custom built for direct Google Sheets integration.
 */

function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu('⚖️ Legal AI Engine')
      .addItem('⚡ Open Sidebar Workspace', 'showSidebar')
      .addItem('⚙️ Clear Current Sheet Matrix', 'clearDashboardMatrix')
      .addToUi();
}

/**
 * Renders and opens the sleek sidebar directly within the active Google Sheet.
 */
function showSidebar() {
  var html = HtmlService.createHtmlOutput(getSidebarHtml())
      .setTitle('Legal Extraction Workspace')
      .setWidth(350);
  SpreadsheetApp.getUi().showSidebar(html);
}

/**
 * Core extraction executor. Reads configuration, calls Gemini API, and
 * writes the structured data directly into your active Google Sheet coordinates.
 */
function runExtractionPipeline(apiKey, overrideText, depth, jurisdiction) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  
  // Save API key securely to UserProperties so the user doesn't have to keep re-entering it
  if (apiKey) {
    PropertiesService.getUserProperties().setProperty('GEMINI_API_KEY', apiKey);
  } else {
    apiKey = PropertiesService.getUserProperties().getProperty('GEMINI_API_KEY');
  }
  
  if (!apiKey) {
    throw new Error("Please provide a valid Gemini API Key.");
  }

  // 1. Resolve source text (read from cell B4, or use sidebar overrides)
  var sourceText = overrideText ? overrideText.trim() : sheet.getRange("B4").getValue().toString().trim();
  if (!sourceText) {
    throw new Error("Source document text is empty. Please paste text in cell B4 or into the sidebar input window.");
  }

  // 2. Fetch parameters directly from Sheet if not overridden
  if (!depth) {
    depth = sheet.getRange("L13").getValue() || "Comprehensive";
  } else {
    sheet.getRange("L13").setValue(depth);
  }
  
  if (!jurisdiction) {
    jurisdiction = sheet.getRange("L14").getValue() || "Federal Jurisdiction";
  } else {
    sheet.getRange("L14").setValue(jurisdiction);
  }

  // 3. Formulate the system instruction rules
  var systemPrompt = "You are a professional, world-class legal AI analysis engine. " +
                     "Extract data from the user-provided legal filing text.\n" +
                     "Extraction parameters: Depth=" + depth + ", Jurisdiction Focus=" + jurisdiction + ".\n\n" +
                     "You MUST output your response strictly as a clean JSON object containing the exact keys listed below. " +
                     "Do not include any markdown styling, code block ticks (```json), preambles, or explanations.\n\n" +
                     "Required JSON Format:\n" +
                     "{\n" +
                     "  \"title\": \"Exact caption name of case\",\n" +
                     "  \"type\": \"Precise legal description of the filing (e.g. Complaint / Breach of Contract)\",\n" +
                     "  \"date\": \"Exact document filing or execution date\",\n" +
                     "  \"court\": \"Filing court or forum name\",\n" +
                     "  \"parties\": \"Detailed Plaintiffs, Defendants, and legal counsel info\",\n" +
                     "  \"authorities\": \"Numbered list of every cited case, statute, or rule\",\n" +
                     "  \"allegations\": \"Numbered list of claims/allegations paired with supporting evidence, exhibits, or paragraph references\",\n" +
                     "  \"relief\": \"Prayer for relief details, including compensatory/punitive damages and fees\"\n" +
                     "}";

  // 4. Fire API call to Gemini Pro / Flash endpoint
  var url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=" + apiKey;
  var payload = {
    "contents": [{
      "parts": [{ "text": systemPrompt + "\n\n[USER DOCUMENT CONTENT]:\n" + sourceText }]
    }],
    "generationConfig": {
      "responseMimeType": "application/json",
      "temperature": 0.1
    }
  };

  var options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };

  var response = UrlFetchApp.fetch(url, options);
  var responseText = response.getContentText();
  var jsonResponse = JSON.parse(responseText);

  if (!jsonResponse.candidates || jsonResponse.candidates.length === 0) {
    throw new Error("API Execution Error: " + responseText);
  }

  var rawOutputText = jsonResponse.candidates[0].content.parts[0].text;
  var cleanJsonStr = rawOutputText.replace(/```json/gi, '').replace(/```/g, '').trim();
  var data = JSON.parse(cleanJsonStr);

  // 5. Directly write results to active Google Sheet cells based on layout mapping
  sheet.getRange("B8").setValue(data.title || "—");
  sheet.getRange("B9").setValue(data.type || "—");
  sheet.getRange("B10").setValue(data.date || "—");
  sheet.getRange("B11").setValue(data.court || "—");
  sheet.getRange("B12").setValue(data.parties || "—");

  sheet.getRange("I20").setValue(data.authorities || "No cited authorities found.");
  sheet.getRange("P20").setValue(data.allegations || "No specific allegations found.");
  sheet.getRange("W20").setValue(data.relief || "No requested relief/prayer found.");

  return "Success! Document extracted and mapped directly to sheet.";
}

/**
 * Utility to clear the matrix coordinates instantly
 */
function clearDashboardMatrix() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var rangesToClear = ["B8", "B9", "B10", "B11", "B12", "I20", "P20", "W20"];
  for (var i = 0; i < rangesToClear.length; i++) {
    sheet.getRange(rangesToClear[i]).setValue("");
  }
}

/**
 * Returns saved API key if available
 */
function getSavedApiKey() {
  return PropertiesService.getUserProperties().getProperty('GEMINI_API_KEY') || '';
}

/**
 * Generates the sleek, responsive UI code for the Google Sheets sidebar panel.
 */
function getSidebarHtml() {
  var savedKey = getSavedApiKey();
  return `
  <!DOCTYPE html>
  <html>
  <head>
    <base target="_top">
    <style>
      body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        padding: 15px;
        background-color: #0f1115;
        color: #e2e8f0;
        margin: 0;
      }
      .title {
        font-size: 14px;
        font-weight: bold;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: #38bdf8;
        border-bottom: 1px solid #1e293b;
        padding-bottom: 8px;
        margin-bottom: 15px;
      }
      .form-group {
        margin-bottom: 12px;
      }
      label {
        display: block;
        font-size: 11px;
        text-transform: uppercase;
        color: #94a3b8;
        margin-bottom: 4px;
        font-weight: 600;
      }
      input, select, textarea {
        width: 100%;
        background-color: #1e293b;
        border: 1px solid #334155;
        color: #f8fafc;
        padding: 8px;
        border-radius: 4px;
        box-sizing: border-box;
        font-size: 12px;
        outline: none;
      }
      input:focus, select:focus, textarea:focus {
        border-color: #38bdf8;
      }
      textarea {
        height: 120px;
        resize: vertical;
      }
      .btn {
        background-color: #0284c7;
        color: white;
        border: none;
        padding: 10px;
        border-radius: 4px;
        cursor: pointer;
        width: 100%;
        font-weight: 600;
        text-transform: uppercase;
        font-size: 11px;
        margin-top: 10px;
        transition: background-color 0.2s;
      }
      .btn:hover {
        background-color: #0369a1;
      }
      .btn-secondary {
        background-color: transparent;
        border: 1px solid #475569;
        color: #cbd5e1;
        margin-top: 5px;
      }
      .btn-secondary:hover {
        background-color: #1e293b;
      }
      .status {
        margin-top: 15px;
        padding: 10px;
        border-radius: 4px;
        font-size: 11px;
        display: none;
      }
      .status-success {
        background-color: #064e3b;
        color: #34d399;
        border: 1px solid #059669;
      }
      .status-error {
        background-color: #7f1d1d;
        color: #fca5a5;
        border: 1px solid #dc2626;
      }
      .status-loading {
        background-color: #1e293b;
        color: #38bdf8;
        border: 1px solid #0284c7;
      }
    </style>
  </head>
  <body>
    <div class="title">⚖️ Extraction Pipeline</div>
    
    <div class="form-group">
      <label>Gemini API Key</label>
      <input type="password" id="apiKey" value="${savedKey}" placeholder="Paste API Key here...">
    </div>

    <div class="form-group">
      <label>Extraction Depth</label>
      <select id="depth">
        <option value="Comprehensive">Comprehensive Analysis</option>
        <option value="Strict Elements Only">Strict Elements Only</option>
      </select>
    </div>

    <div class="form-group">
      <label>Jurisdiction Focus</label>
      <select id="jurisdiction">
        <option value="Federal Jurisdiction">Federal focus</option>
        <option value="State Jurisdiction">State focus</option>
      </select>
    </div>

    <div class="form-group">
      <label>OCR Input Override (Optional)</label>
      <textarea id="overrideText" placeholder="Leave blank to use the text already inside cell B4..."></textarea>
    </div>

    <button class="btn" id="runBtn" onclick="executeScrape()">Run Legal Extraction</button>
    <button class="btn btn-secondary" onclick="clearSheet()">Clear Output Cells</button>

    <div class="status" id="statusBox"></div>

    <script>
      function executeScrape() {
        var apiKey = document.getElementById('apiKey').value.trim();
        var depth = document.getElementById('depth').value;
        var jurisdiction = document.getElementById('jurisdiction').value;
        var overrideText = document.getElementById('overrideText').value;
        
        var statusBox = document.getElementById('statusBox');
        var runBtn = document.getElementById('runBtn');
        
        statusBox.style.display = 'block';
        statusBox.className = 'status status-loading';
        statusBox.innerText = 'Extracting elements... Please wait.';
        runBtn.disabled = true;
        
        google.script.run
          .withSuccessHandler(function(result) {
            statusBox.className = 'status status-success';
            statusBox.innerText = result;
            runBtn.disabled = false;
          })
          .withFailureHandler(function(error) {
            statusBox.className = 'status status-error';
            statusBox.innerText = 'Error: ' + error.message;
            runBtn.disabled = false;
          })
          .runExtractionPipeline(apiKey, overrideText, depth, jurisdiction);
      }

      function clearSheet() {
        google.script.run.clearDashboardMatrix();
        var statusBox = document.getElementById('statusBox');
        statusBox.style.display = 'block';
        statusBox.className = 'status status-loading';
        statusBox.innerText = 'Spreadsheet coordinates cleared.';
      }
    </script>
  </body>
  </html>
  `;
}