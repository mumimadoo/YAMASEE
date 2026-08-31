const fs = require('fs');
const path = require('path');

// Extract item data returned by real API
const realApiItem = {
  "id": 18,
  "user_id": 14,
  "user_username": "super",
  "date_time": "2026-08-17T15:20:23.992218+07:00",
  "source_type": "youtube",
  "url_or_filename": "https://youtu.be/M4Cb4OOXtJ8?si=nVkcgVpluvhsKJlY",
  "model_used": "gemini-3.5-flash",
  "video_duration": 347.6,
  "processing_time": 630.510768,
  "total_words": 224,
  "words_per_minute": 38.66513233601841,
  "job_id": "job_1786954193_f2b616",
  "api_calls": 18,
  "estimated_cost": 1.5735,
  "estimated_cost_version": "v1",
  "token_usage": {
    "transcription": {
      "requests": 17,
      "prompt_tokens": 15507,
      "candidates_tokens": 3300,
      "cached_tokens": 0,
      "thoughts_tokens": 10231,
      "total_tokens": 29038
    },
    "analysis": {
      "requests": 1,
      "prompt_tokens": 2445,
      "candidates_tokens": 1167,
      "cached_tokens": 0,
      "thoughts_tokens": 2127,
      "total_tokens": 5739
    },
    "job_total": {
      "requests": 18,
      "prompt_tokens": 17952,
      "candidates_tokens": 4467,
      "cached_tokens": 0,
      "thoughts_tokens": 12358,
      "total_tokens": 34777
    },
    "models": {
      "gemini-3.5-flash": {
        "requests": 17,
        "prompt_tokens": 16850,
        "candidates_tokens": 4215,
        "cached_tokens": 0,
        "thoughts_tokens": 12310,
        "total_tokens": 33375
      },
      "gemini-2.5-flash": {
        "requests": 1,
        "prompt_tokens": 1102,
        "candidates_tokens": 252,
        "cached_tokens": 0,
        "thoughts_tokens": 48,
        "total_tokens": 1402
      }
    }
  }
};

const oldApiItem = {
  "id": 1,
  "user_id": 14,
  "user_username": "super",
  "job_id": "job_old_123",
  "api_calls": 5,
  "estimated_cost": 0.5,
  "token_usage": null
};

// Simulate tdToken rendering logic from static/js/admin.js
function renderTdToken(item) {
    let tu = item.token_usage;
    if (typeof tu === 'string') {
        try { tu = JSON.parse(tu); } catch (e) { tu = null; }
    }

    if (tu && typeof tu === 'object' && tu.job_total) {
        const jobTot = tu.job_total || {};
        const total = jobTot.total_tokens !== undefined ? jobTot.total_tokens.toLocaleString() : '0';
        const prompt = jobTot.prompt_tokens !== undefined ? jobTot.prompt_tokens.toLocaleString() : '0';
        const output = jobTot.candidates_tokens !== undefined ? jobTot.candidates_tokens.toLocaleString() : '0';
        const thinking = jobTot.thoughts_tokens !== undefined ? jobTot.thoughts_tokens.toLocaleString() : '0';
        const cached = jobTot.cached_tokens !== undefined ? jobTot.cached_tokens.toLocaleString() : '0';

        return `<div><div>Total: <strong>${total}</strong></div><div>Prompt: ${prompt}</div><div>Output: ${output}</div><div>Thinking: ${thinking}</div><div>Cached: ${cached}</div><button>ดูการใช้ Token</button></div>`;
    } else {
        return `<span>ไม่มีข้อมูล</span>`;
    }
}

console.log("--- REAL JOB TOKEN CELL RENDER ---");
console.log(renderTdToken(realApiItem));

console.log("\n--- OLD JOB TOKEN CELL RENDER ---");
console.log(renderTdToken(oldApiItem));
