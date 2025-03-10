import os
import hashlib
import pickle
import asyncio
import aiohttp
from dotenv import load_dotenv
import streamlit as st
from datetime import datetime
import json
import time
import threading
import anthropic
import requests

# Load environment variables
load_dotenv()
# With this:
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

# Initialize Anthropic client directly
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Create cache directory
os.makedirs("cache", exist_ok=True)

def get_cache_key(query):
    """Generate a cache key from a search query"""
    return hashlib.md5(query.encode()).hexdigest()

async def fetch_search_results(session, query, num_results=5):
    """Fetch search results asynchronously"""
    url = "https://serpapi.com/search"
    
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPER_API_KEY,
        "num": num_results
    }
    
    try:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                results = await response.json()
                
                # Extract organic results
                organic_results = []
                if "organic_results" in results:
                    for result in results["organic_results"][:num_results]:
                        organic_results.append({
                            "title": result.get("title", ""),
                            "link": result.get("link", ""),
                            "snippet": result.get("snippet", "")
                        })
                
                return {"query": query, "results": organic_results}
            else:
                return {"query": query, "results": []}
    except Exception as e:
        return {"query": query, "results": []}

async def search_web_async(queries):
    """Search the web for multiple queries asynchronously"""
    # Check cache first
    cached_results = {}
    queries_to_fetch = []
    
    for query in queries:
        cache_key = get_cache_key(query)
        cache_file = f"cache/{cache_key}.pkl"
        
        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as f:
                cached_results[query] = pickle.load(f)
        else:
            queries_to_fetch.append(query)
    
    # Fetch results for queries not in cache
    if queries_to_fetch:
        async with aiohttp.ClientSession() as session:
            tasks = [fetch_search_results(session, query) for query in queries_to_fetch]
            fetched_results = await asyncio.gather(*tasks)
            
            # Update cache with fetched results
            for result in fetched_results:
                query = result["query"]
                cache_key = get_cache_key(query)
                cache_file = f"cache/{cache_key}.pkl"
                
                with open(cache_file, 'wb') as f:
                    pickle.dump(result["results"], f)
                
                cached_results[query] = result["results"]
    
    # Return all results
    return {query: cached_results.get(query, []) for query in queries}

def estimate_tokens(text):
    """Estimate token count for a text string - rough approximation"""
    # Claude uses ~4 chars per token on average
    return len(text) // 4

def filter_search_results(results, max_tokens=800):
    """Filter search results to stay within token budget"""
    filtered_results = {}
    current_tokens = 0
    
    for query, query_results in results.items():
        filtered_query_results = []
        
        for result in query_results:
            # Estimate tokens for this result
            result_text = f"{result['title']}\n{result['snippet']}\nSource: {result['link']}\n\n"
            result_tokens = estimate_tokens(result_text)
            
            # Add if within budget
            if current_tokens + result_tokens <= max_tokens:
                filtered_query_results.append(result)
                current_tokens += result_tokens
            else:
                break
        
        filtered_results[query] = filtered_query_results
        
        # Stop if we've reached the token budget
        if current_tokens >= max_tokens:
            break
    
    return filtered_results, current_tokens

def format_search_results(results, industry, target_audience, content_goals):
    """Format search results for Claude with optimized token usage"""
    formatted_text = "RECENT WEB SEARCH RESULTS:\n\n"
    
    # Format industry results
    industry_query = f"latest trends in {industry} industry {datetime.now().year}"
    if industry_query in results and results[industry_query]:
        formatted_text += f"INDUSTRY TRENDS FOR {industry.upper()}:\n"
        for i, result in enumerate(results[industry_query]):
            formatted_text += f"{i+1}. {result['title']}\n   {result['snippet'][:150]}...\n\n"
    
    # Format audience results
    audience_query = f"content marketing for {target_audience} {datetime.now().year}"
    if audience_query in results and results[audience_query]:
        formatted_text += f"\nCONTENT FOR {target_audience.upper()}:\n"
        for i, result in enumerate(results[audience_query]):
            formatted_text += f"{i+1}. {result['title']}\n   {result['snippet'][:150]}...\n\n"
    
    # Format goals results
    goals_query = f"{content_goals} content strategy examples {datetime.now().year}"
    if goals_query in results and results[goals_query]:
        formatted_text += f"\nSTRATEGIES FOR {content_goals.upper()}:\n"
        for i, result in enumerate(results[goals_query]):
            formatted_text += f"{i+1}. {result['title']}\n   {result['snippet'][:150]}...\n\n"
    
    return formatted_text

async def run_content_calendar_creation(industry, target_audience, content_goals, progress_callback=None):
    """Generate content calendar using optimized single API call with async web search"""
    try:
        start_time = datetime.now()
        
        # Update progress
        if progress_callback:
            progress_callback(10, "Searching for current trends...")
        
        # Prepare search queries
        search_queries = [
            f"latest trends in {industry} industry {datetime.now().year}",
            f"content marketing for {target_audience} {datetime.now().year}",
            f"{content_goals} content strategy examples {datetime.now().year}"
        ]
        
        # Execute async web searches
        search_results = await search_web_async(search_queries)
        
        # Update progress
        if progress_callback:
            progress_callback(40, "Processing search results...")
        
        # Filter and format search results to stay within token budget
        filtered_results, token_count = filter_search_results(search_results)
        formatted_search_results = format_search_results(filtered_results, industry, target_audience, content_goals)
        
        # Update progress
        if progress_callback:
            progress_callback(60, "Generating content calendar...")
        
        # Create a comprehensive single prompt for all three steps
        combined_prompt = f"""Generate a complete 7-day content calendar for the {industry} industry targeting {target_audience} with goals to {content_goals}.

Use this real-time research data to inform your response:

{formatted_search_results}

Please structure your response in these three distinct sections:

SECTION 1: RESEARCH INSIGHTS
Identify current trends in the {industry} industry relevant to {target_audience}.
- Top content formats (video, blog, etc.)
- Trending topics and hashtags
- Upcoming events in the next 2 weeks
- 5-7 potential content topics that align with: {content_goals}

SECTION 2: 7-DAY CONTENT CALENDAR
Create a strategic 7-day content plan.
- Mix of content types (educational, promotional, etc.)
- One main topic per day
- Brief rationale for each day
Format as Day 1: [Topic] - [Type] - [Brief rationale]

SECTION 3: CONTENT BRIEFS
For each day, provide:
- Headline
- Brief hook
- 3-5 key points
- Call-to-action

Keep your response concise and actionable, focused on practical implementation.
"""
        
        # Send single API request to Claude
        response = client.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=2000,
            temperature=0.7,
            system="You are an expert content marketer who creates strategic, audience-focused content calendars based on industry trends and business goals.",
            messages=[
                {"role": "user", "content": combined_prompt}
            ]
        )
        
        # Extract results
        calendar_content = response.content[0].text
        
        # Update progress
        if progress_callback:
            progress_callback(100, "Content calendar completed!")
        
        # Calculate token usage and execution time
        prompt_tokens = estimate_tokens(combined_prompt)
        response_tokens = estimate_tokens(calendar_content)
        execution_time = (datetime.now() - start_time).total_seconds()
        
        # Calculate costs (based on Claude 3.7 Sonnet pricing)
        input_cost = (prompt_tokens / 1000000) * 15  # $15 per million input tokens
        output_cost = (response_tokens / 1000000) * 75  # $75 per million output tokens
        total_cost = input_cost + output_cost
        
        return {
            'result': calendar_content,
            'execution_time': execution_time,
            'tokens': {
                'input': prompt_tokens,
                'output': response_tokens,
                'total': prompt_tokens + response_tokens
            },
            'estimated_cost': total_cost
        }
    except Exception as e:
        return f"Error: {str(e)}"

def save_content_calendar(industry, target_audience, content_goals, result, metrics=None):
    """Save content calendar to JSON file with performance metrics"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"content_calendar_{timestamp}.json"
    
    data = {
        "industry": industry,
        "target_audience": target_audience,
        "content_goals": content_goals,
        "timestamp": timestamp,
        "content_calendar": result
    }
    
    # Add performance metrics if available
    if metrics:
        data["performance_metrics"] = metrics
    
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)
    
    return filename

def main():
    st.set_page_config(page_title="7-Day Content Calendar Creator", layout="wide")
    
    st.title("📅 AI Content Calendar Creator")
    st.subheader("Powered by Claude 3.7 Sonnet")
    
    # Input form with character counters
    with st.form("content_calendar_form"):
        industry = st.text_input("Industry/Niche (max 100 chars)", placeholder="e.g., Fitness, SaaS, Digital Marketing")
        st.caption(f"Characters: {len(industry)}/100")
        
        target_audience = st.text_area("Target Audience (max 200 chars)", placeholder="Key demographics and interests...", height=80)
        st.caption(f"Characters: {len(target_audience)}/200")
        
        content_goals = st.text_area("Content Goals (max 200 chars)", placeholder="e.g., Increase brand awareness...", height=80)
        st.caption(f"Characters: {len(content_goals)}/200")
        
        submit_button = st.form_submit_button("Generate 7-Day Content Calendar")
    
    if submit_button:
        if not industry or not target_audience or not content_goals:
            st.error("Please fill out all fields")
            return
        
        # Create progress tracking
        progress_bar = st.progress(0)
        status_container = st.empty()
        metrics_container = st.empty()
        status_container.info("Starting content calendar creation...")
        start_time = datetime.now()
        
        # Progress callback
        def update_progress(progress, status_text):
            progress_bar.progress(progress)
            status_container.info(f"{status_text} ({(datetime.now() - start_time).total_seconds():.1f}s)")
        
        # Run the optimized content calendar creation
        result = asyncio.run(run_content_calendar_creation(
            industry, 
            target_audience, 
            content_goals,
            update_progress
        ))
        
        if isinstance(result, dict) and 'result' in result:
            # Display performance metrics
            token_info = result.get('tokens', {})
            cost_info = result.get('estimated_cost', 0)
            
            metrics_md = f"""
            ### ⚡ Performance Metrics
            - **Execution Time:** {result['execution_time']:.2f} seconds
            - **Token Usage:** {token_info.get('total', 0):,} total tokens
            - **Estimated Cost:** ${cost_info:.4f}
            """
            metrics_container.markdown(metrics_md)
            
            # Save results to file with metrics
            metrics = {
                "execution_time_seconds": result['execution_time'],
                "tokens": token_info,
                "estimated_cost_usd": cost_info
            }
            filename = save_content_calendar(industry, target_audience, content_goals, result['result'], metrics)
            
            # Show results
            st.subheader("Your 7-Day Content Calendar")
            st.write(result['result'])
            
            # Create a download button for the JSON file
            with open(filename, "r") as f:
                st.download_button(
                    label="Download Content Calendar (JSON)",
                    data=f,
                    file_name=filename,
                    mime="application/json"
                )
            
        else:
            progress_bar.progress(100)
            status_container.error(f"Error: {result}")
            metrics_container.empty()

if __name__ == "__main__":
    main()