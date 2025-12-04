"""
Erica AI Tutor - Streamlit Chat Interface

Usage:
    streamlit run src/app.py
"""

import streamlit as st
import re
import sys
sys.path.insert(0, '/app')

from src.retrieval.hybrid_retriever import HybridRetriever
from src.generation.answer_generator import AnswerGenerator


def convert_latex_delimiters(text: str) -> str:
    """
    Convert LaTeX delimiters from \( \) and \[ \] to $ and $$ for Streamlit.
    """
    # Convert \[ ... \] to $$ ... $$ (block math)
    text = re.sub(r'\\\[(.*?)\\\]', r'$$\1$$', text, flags=re.DOTALL)
    
    # Convert \( ... \) to $ ... $ (inline math)
    text = re.sub(r'\\\((.*?)\\\)', r'$\1$', text, flags=re.DOTALL)
    
    return text


# Page config
st.set_page_config(
    page_title="Erica - AI Tutor",
    page_icon="🎓",
    layout="wide",
)

# Title
st.title("🎓 Erica - Your AI Tutor")
st.caption("Ask questions about AI/ML concepts from the Introduction to AI course")


@st.cache_resource
def load_retriever():
    """Load retriever (cached to avoid reloading)."""
    return HybridRetriever(
        mongo_uri="mongodb://erica:erica_password_123@mongodb:27017/",
        chroma_host="chromadb",
        neo4j_uri="bolt://neo4j:7687",
    )


@st.cache_resource
def load_generator():
    """Load generator (cached to avoid reloading)."""
    return AnswerGenerator()


# Initialize session state for chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

if "retrieval_results" not in st.session_state:
    st.session_state.retrieval_results = []


# Sidebar with settings and info
with st.sidebar:
    st.header("⚙️ Settings")
    
    top_k = st.slider("Semantic search results", 3, 10, 5)
    prereq_depth = st.slider("Prerequisite depth", 1, 3, 2)
    max_concepts = st.slider("Max concepts", 10, 25, 15)
    
    st.divider()
    
    st.header("📊 Knowledge Graph Stats")
    
    try:
        retriever = load_retriever()
        stats = retriever.embedder.get_stats()
        st.metric("Concepts in ChromaDB", stats.get("count", "N/A"))
    except Exception as e:
        st.error(f"Could not load stats: {e}")
    
    st.divider()
    
    if st.button("🗑️ Clear Chat"):
        st.session_state.messages = []
        st.session_state.retrieval_results = []
        st.rerun()
    
    st.divider()
    st.caption("Built with GraphRAG for Introduction to AI")


# Display chat history
for i, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        content = message["content"]
        if message["role"] == "assistant":
            content = convert_latex_delimiters(content)
        st.markdown(content)
        
        # Show retrieval details for assistant messages
        if message["role"] == "assistant":
            # Calculate result index (each Q&A pair has one result)
            result_idx = i // 2
            if result_idx < len(st.session_state.retrieval_results):
                result = st.session_state.retrieval_results[result_idx]
                with st.expander("📚 View Retrieved Context"):
                    st.write("**Seed Concepts:**")
                    for match in result.semantic_matches[:5]:
                        st.write(f"- {match['title']} (score: {match['score']:.3f})")
                    
                    st.write("**Explanation Order:**")
                    st.write(" → ".join(result.ordered_concepts[:8]))
                    
                    st.write(f"**Resources:** {len(result.subgraph.resources)}")
                    st.write(f"**Examples:** {len(result.subgraph.examples)}")


# Chat input
if prompt := st.chat_input("Ask a question about AI/ML..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Generate response
    with st.chat_message("assistant"):
        with st.spinner("🔍 Searching knowledge graph..."):
            try:
                retriever = load_retriever()
                generator = load_generator()
                
                result = retriever.retrieve(
                    query=prompt,
                    top_k_semantic=top_k,
                    prereq_depth=prereq_depth,
                    max_concepts=max_concepts,
                )
                
                st.session_state.retrieval_results.append(result)
                
            except Exception as e:
                st.error(f"Retrieval error: {e}")
                st.stop()
        
        with st.spinner("💭 Generating answer..."):
            try:
                answer = generator.generate(result)
                display_answer = convert_latex_delimiters(answer)
                st.markdown(display_answer)
                
                # Save original to history
                st.session_state.messages.append({"role": "assistant", "content": answer})
                
            except Exception as e:
                st.error(f"Generation error: {e}")
                st.stop()
        
        # Show retrieval details
        with st.expander("📚 View Retrieved Context"):
            st.write("**Seed Concepts:**")
            for match in result.semantic_matches[:5]:
                st.write(f"- {match['title']} (score: {match['score']:.3f})")
            
            st.write("**Explanation Order:**")
            st.write(" → ".join(result.ordered_concepts[:8]))
            
            st.write(f"**Resources:** {len(result.subgraph.resources)}")
            st.write(f"**Examples:** {len(result.subgraph.examples)}")