# Azure Document Intelligence Rate Limits & Quota Guide

## Executive Summary

Your Azure OCR is hitting **rate limits** if you're processing more than **15 concurrent requests per second**.

---

## 🚨 Rate Limits by Pricing Tier

### Free Tier (F0)
| Limit | Value |
|-------|-------|
| **Analyze Transactions/Second** | 1 TPS |
| **Get Operations/Second** | 1 TPS |
| **Max Document Size** | 4 MB |
| **Max Pages per Request** | 2 pages (ONLY) |
| **Status** | NOT adjustable |

❌ **Not suitable for production** - can only process 2 pages max

---

### Standard Tier (S0) - YOUR TIER
| Limit | Value | Adjustable? |
|-------|-------|-------------|
| **Analyze Transactions/Second (POST)** | **15 TPS (default)** | ✅ YES |
| **Get Operations/Second (GET)** | **50 TPS (default)** | ✅ YES |
| **Model Management Ops/Second** | 5 TPS | ✅ YES |
| **List Operations/Second** | 10 TPS | ✅ YES |
| **Max Document Size** | 500 MB | ❌ NO |
| **Max Pages per Request** | 2,000 pages | ❌ NO |

---

## 📊 What Are These Limits?

### **1. Analyze Transactions/Second (POST) - 15 TPS**
- This is where **you're likely hitting the limit**
- Each document you submit = 1 transaction (not per page)
- **Your 150-page PDF** = 1 transaction = 1 TPS usage
- At **15 TPS**: You can submit 15 documents simultaneously

#### Example Scenario:
```
If you send 20 PDFs at the same time:
└─ 20 transactions attempted
└─ Only 15 can be processed immediately
└─ Remaining 5 get 429 Error (Too Many Requests) ❌
```

---

### **2. Get Operations/Second (GET) - 50 TPS**
- Checking the status/result of processing
- Usually not the bottleneck (higher limit than POST)

---

## 🔍 How to Know If You're Hit Rate Limit

### Error Response:
```
HTTP 429 Too Many Requests
{
  "error": {
    "code": "429",
    "message": "Rate limit exceeded"
  }
}
```

### In Your Code (Python):
```python
requests.exceptions.HTTPError: 429 Client Error: Too Many Requests
```

### Check Usage in Azure Portal:
1. Go to Azure Portal
2. Navigate to your **Document Intelligence resource**
3. Click **Monitoring** → **Metrics**
4. Look for transaction counts and throttling events

---

## 💥 Problem: Your Batch Processing

Looking at your `batch_process.py`:

```python
async def run_batch(pdf_dir: str = "PDF") -> None:
    pdf_files = sorted(...)
    for pdf_path in pdf_files:
        result = await process_single_pdf(pdf_path)  # ← Sequential, OK
```

**Current Status**: ✅ **SAFE**
- Processing one PDF at a time (sequential)
- Using 1 TPS per PDF
- Well below 15 TPS limit

**But if you tried parallel processing:**
```python
# DON'T DO THIS - will hit rate limit!
results = await asyncio.gather(*[
    process_single_pdf(pdf) for pdf in pdf_files
])  # ← If >15 PDFs, you'll get 429 errors
```

---

## ⚡ Solutions to Handle Rate Limits

### **Solution 1: Implement Retry Logic with Exponential Backoff** (Recommended)

```python
import time
from functools import wraps

def retry_with_backoff(max_retries=3):
    """Retry failed requests with exponential backoff."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            backoff_delays = [2, 5, 13, 34]  # Exponential backoff pattern
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except HTTPError as e:
                    if e.response.status_code == 429:
                        if attempt < max_retries - 1:
                            wait_time = backoff_delays[attempt] if attempt < len(backoff_delays) else 60
                            print(f"Rate limited. Waiting {wait_time}s...")
                            await asyncio.sleep(wait_time)
                        else:
                            raise
                    else:
                        raise
        return wrapper
    return decorator

@retry_with_backoff(max_retries=3)
async def process_single_pdf(pdf_path: str) -> dict:
    # Your existing code
    return await main.generate_report_endpoint(upload)
```

---

### **Solution 2: Implement Throttling (Queue-Based)**

```python
import asyncio
from asyncio import Semaphore

# Limit concurrent requests to 10 (safe, below 15 TPS limit)
semaphore = Semaphore(10)

async def process_with_limit(pdf_path: str):
    async with semaphore:
        return await process_single_pdf(pdf_path)

async def run_batch(pdf_dir: str = "PDF") -> None:
    pdf_files = sorted(...)
    tasks = [process_with_limit(pdf) for pdf in pdf_files]
    
    # Process up to 10 concurrently, queue the rest
    results = await asyncio.gather(*tasks, return_exceptions=True)
```

---

### **Solution 3: Request TPS Increase from Azure** (If needed)

For **high-volume production**, request TPS increase:

**Step 1**: Open Azure Support Request
- Portal → Your Document Intelligence Resource
- **Support + troubleshooting** → **New support request**
- Problem type: **"Quota or usage validation"**

**Step 2**: In description, specify:
```
Request: Increase Document Intelligence TPS limit
Current: 15 TPS (default)
Requested: 50 TPS (or higher)
Reason: Processing 150-page PDF batches at high volume
Expected Load: [Your volume here]
```

**Step 3**: Azure will review and approve (usually within 2-3 days)

---

## 📈 Scaling Scenarios

### Scenario 1: Processing 10 PDFs Sequentially (Current Setup)
```
10 PDFs × 1 TPS per PDF = 10 TPS total usage ✅ OK
```

### Scenario 2: Processing 10 PDFs in Parallel (Concurrent)
```
10 concurrent requests = 10 TPS ✅ OK (below 15 TPS)
```

### Scenario 3: Processing 20 PDFs in Parallel
```
20 concurrent requests = 20 TPS ❌ HITS LIMIT
└─ First 15 succeed
└─ Remaining 5 get 429 error
```

### Scenario 4: Processing 150 PDFs in Parallel
```
150 concurrent requests = 150 TPS ❌ MASSIVE THROTTLING
└─ Only 15 process, 135 queue/retry
└─ Expect heavy delays and retries
```

---

## ✅ Best Practices (from Azure Docs)

1. **Implement retry logic** with exponential backoff (2-5-13-34 second pattern)
2. **Don't send sharp workload increases** - gradually ramp up
3. **Space out requests** - add small delays between submissions
4. **Use semaphore/queue** to limit concurrent requests to safe levels (8-10)
5. **Monitor in Azure Portal** - watch Metrics tab for throttling events
6. **Request increase early** if you know high volume is coming

---

## 🛠️ Recommended Implementation for Your Pipeline

Add this to your `batch_process.py`:

```python
import asyncio
from asyncio import Semaphore
from typing import List

# Limit to 10 concurrent (safe, below 15 TPS)
REQUEST_SEMAPHORE = Semaphore(10)

async def process_single_pdf_with_limit(pdf_path: str) -> dict:
    """Process PDF with rate limiting."""
    async with REQUEST_SEMAPHORE:
        filename = os.path.basename(pdf_path)
        with open(pdf_path, "rb") as stream:
            upload = UploadFile(
                filename=filename,
                file=stream,
                headers=Headers({"content-type": "application/pdf"}),
            )
            return await main.generate_report_endpoint(upload)

async def run_batch_with_rate_limit(pdf_dir: str = "PDF", max_concurrent: int = 10) -> None:
    """Process batch with rate limiting and retry logic."""
    pdf_files = sorted(
        os.path.join(pdf_dir, name)
        for name in os.listdir(pdf_dir)
        if name.lower().endswith(".pdf")
    )
    
    if not pdf_files:
        print(f"No PDF files found in {pdf_dir}.")
        return
    
    print(f"Processing {len(pdf_files)} PDFs with {max_concurrent} concurrent limit...")
    
    # Create tasks with semaphore
    tasks = [process_single_pdf_with_limit(pdf) for pdf in pdf_files]
    
    # Process with error handling
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for idx, (pdf_path, result) in enumerate(zip(pdf_files, results)):
        if isinstance(result, Exception):
            print(f"❌ Failed: {os.path.basename(pdf_path)}: {result}")
        else:
            print(f"✅ Generated: {result.get('pdf_path')}")
```

---

## 📞 Contact Azure Support

If you consistently hit rate limits:

1. **Check current usage**: Azure Portal → Resource → Monitoring → Metrics
2. **Document your workload**: When do you send requests? How many? Volume patterns?
3. **Open support ticket**: Request TPS increase with business justification
4. **Expected increase time**: 2-3 business days

---

## Summary Table

| Issue | Limit | Solution |
|-------|-------|----------|
| 429 Error on batch processing | 15 TPS POST limit | Add retry logic + semaphore |
| Too many PDFs at once | 15 concurrent | Queue/throttle to 8-10 concurrent |
| Sustained high volume | Hard limit at 15 TPS | Request TPS increase from Azure |
| Payment/cost concerns | N/A | Rate limits are FREE quota increases |

---

## References
- [Official Azure Service Limits](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits?view=doc-intel-4.0.0)
- [Support Request Process](https://learn.microsoft.com/en-us/answers/questions/5579694/increase-document-intelligence-tps-limit)
