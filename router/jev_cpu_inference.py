import json
import time
import logging
from typing import List, Dict, Any, Optional
from llama_cpp import Llama

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("JevRouter")

class JevCPURouter:
    """
    System One deterministic CPU router for Kingsfield Lawfare.
    Executes Choice, Noul, and Score primitives locally without network calls.
    Optimized for Intel x86_64 Mac processors.
    """
    def __init__(self, model_path: str, n_ctx: int = 1024, n_threads: int = 4):
        logger.info(f"Loading local JEV model from {model_path} on {n_threads} threads...")
        self.llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads, 
            verbose=False        
        )

    def _generate(self, prompt: str, max_tokens: int = 10) -> str:
        response = self.llm(
            prompt,
            max_tokens=max_tokens,
            stop=["\n", "</s>"],
            echo=False,
            temperature=0.0 
        )
        return response["choices"][0]["text"].strip()

    def choice(self, text: str, options: List[str]) -> str:
        valid_options = ", ".join([f"'{opt}'" for opt in options])
        prompt = (
            f"Classify the following text into exactly one of these categories: {valid_options}.\n\n"
            f"Text: \"{text}\"\n"
            f"Category:"
        )
        result = self._generate(prompt, max_tokens=10)
        
        for opt in options:
            if opt.lower() in result.lower():
                return opt
        return options[0]

    def noul(self, text: str) -> bool:
        prompt = (
            f"Does the following text contain a formal legal citation (e.g., '100 So. 3d 200')? "
            f"Answer strictly 'Yes' or 'No'.\n\n"
            f"Text: \"{text}\"\n"
            f"Answer:"
        )
        result = self._generate(prompt, max_tokens=2).lower()
        return "yes" in result

    def score(self, text: str, proposition: str) -> float:
        prompt = (
            f"Rate how strongly the given Text supports the Proposition on a scale of 0.0 to 1.0. "
            f"Output ONLY the number.\n\n"
            f"Text: \"{text}\"\n"
            f"Proposition: \"{proposition}\"\n"
            f"Score:"
        )
        result = self._generate(prompt, max_tokens=5)
        try:
            return float(''.join(c for c in result if c.isdigit() or c == '.'))
        except ValueError:
            return 0.0

if __name__ == "__main__":
    MODEL_PATH = "qwen1_5-0_5b-chat-q4_k_m.gguf" 
    
    try:
        router = JevCPURouter(model_path=MODEL_PATH)
        
        prose_test = router.noul("She has served 12 So. Fla. counties since 2010.")
        print(f"Noul Test (Prose Leak): {'Pass' if not prose_test else 'Fail (False Positive)'}")
        
        jurisdiction = router.choice("Smith v. State, 100 So. 3d 200 (Fla. 4th DCA 2012)", ["Florida", "Alabama", "Other"])
        print(f"Choice Test: {jurisdiction}")
        
    except Exception as e:
        print(f"To run this locally, ensure llama-cpp-python is installed: pip install llama-cpp-python")
        print(f"Error: {e}")
