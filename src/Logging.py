from langchain.callbacks.base import BaseCallbackHandler
import time
import logging
import pprint

class LoggingCallbackHandler(BaseCallbackHandler):
    """Enhanced callback handler that logs LangChain/LangGraph events to a Python logger"""
    
    def __init__(self, logger):
        self.logger = logger
        self.step_counts = {
            "llm": 0,
            "chain": 0,
            "tool": 0,
            "retriever": 0
        }
        self.start_times = {}
        
    def _format_dict(self, obj, max_length=None): 
        """Format dictionaries"""
        if isinstance(obj, dict):
            formatted = {}
            for k, v in obj.items():
                if isinstance(v, dict):
                    formatted[k] = self._format_dict(v)
                else:
                    formatted[k] = v
            return formatted
        return obj
    
    def _get_elapsed_time(self, event_id):
        """Calculate elapsed time for an event in ms"""
        if event_id in self.start_times:
            elapsed = (time.time() - self.start_times[event_id]) * 1000
            del self.start_times[event_id]
            return f"({elapsed:.2f}ms)"
        return ""
        
    # LLM events
    def on_llm_start(self, serialized, prompts, **kwargs):
        """Log when an LLM starts processing"""
        self.step_counts["llm"] += 1
        event_id = f"llm_{self.step_counts['llm']}"
        self.start_times[event_id] = time.time()
        
        model = serialized.get("id", ["unknown"])[-1]
        self.logger.debug(f"[LLM START] Model: {model}, Prompt tokens: {len(''.join(prompts))//4}")
        
        if prompts and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"[LLM PROMPT] {prompts[0]}") 
        
    def on_llm_end(self, response, **kwargs):
        """Log when an LLM completes processing"""
        event_id = f"llm_{self.step_counts['llm']}"
        elapsed = self.__get_elapsed_time(event_id)
        
        # Extract token usage when available
        token_info = ""
        if hasattr(response, 'llm_output') and response.llm_output:
            usage = response.llm_output.get('token_usage', {})
            if usage:
                token_info = f"(Input: {usage.get('prompt_tokens', '?')}, " \
                             f"Output: {usage.get('completion_tokens', '?')}, " \
                             f"Total: {usage.get('total_tokens', '?')})"
        
        self.logger.debug(f"[LLM END] {elapsed} {token_info}")
        
        if hasattr(response, 'generations') and response.generations:
            for i, gen in enumerate(response.generations[0]):
                if hasattr(gen, 'text'):
                    self.logger.debug(f"[LLM GEN {i+1}] {gen.text}")  # No truncation
                    
    def on_llm_error(self, error, **kwargs):
        """Log when an LLM encounters an error"""
        self.logger.error(f"[LLM ERROR] {str(error)}")
    
    # Chain events
    def on_chain_start(self, serialized, inputs, **kwargs):
        """Log when a chain starts processing"""
        self.step_counts["chain"] += 1
        event_id = f"chain_{self.step_counts['chain']}"
        self.start_times[event_id] = time.time()
        
        chain_name = kwargs.get('name', serialized.get('id', ['unnamed'])[-1])
        self.logger.debug(f"[CHAIN START] {chain_name}")
        
        if self.logger.isEnabledFor(logging.DEBUG):
            formatted_inputs = self._format_dict(inputs)
            self.logger.debug(f"[CHAIN INPUTS] {pprint.pformat(formatted_inputs, compact=True)}")  # No truncation
            
    def on_chain_end(self, outputs, **kwargs):
        """Log when a chain completes"""
        chain_name = kwargs.get('name', 'unnamed')
        event_id = f"chain_{self.step_counts['chain']}"
        elapsed = self._get_elapsed_time(event_id)
        
        self.logger.debug(f"[CHAIN END] {chain_name} {elapsed}")
        
        if self.logger.isEnabledFor(logging.DEBUG):
            formatted_outputs = self._format_dict(outputs)
            self.logger.debug(f"[CHAIN OUTPUTS] {pprint.pformat(formatted_outputs, compact=True)}")  # No truncation
            
    def on_chain_error(self, error, **kwargs):
        """Log when a chain encounters an error"""
        chain_name = kwargs.get('name', 'unnamed')
        self.logger.error(f"[CHAIN ERROR] {chain_name}: {str(error)}")
        
        # Include traceback for debugging
        import traceback
        self.logger.error(f"[CHAIN ERROR TRACE] {traceback.format_exc()}")
    
    # Tool events
    def on_tool_start(self, serialized, input_str, **kwargs):
        """Log when a tool starts execution"""
        self.step_counts["tool"] += 1
        event_id = f"tool_{self.step_counts['tool']}"
        self.start_times[event_id] = time.time()
        
        tool_name = kwargs.get('name', serialized.get('name', 'unnamed_tool'))
        self.logger.debug(f"[TOOL START] {tool_name}: {input_str}") 
        
    def on_tool_end(self, output, **kwargs):
        """Log when a tool completes execution"""
        tool_name = kwargs.get('name', 'unnamed_tool')
        event_id = f"tool_{self.step_counts['tool']}"
        elapsed = self._get_elapsed_time(event_id)
        
        if isinstance(output, str):
            output_str = output
        else:
            output_str = str(output)
            
        self.logger.debug(f"[TOOL END] {tool_name} {elapsed}: {output_str}") 
        
    def on_tool_error(self, error, **kwargs):
        """Log when a tool encounters an error"""
        tool_name = kwargs.get('name', 'unnamed_tool')
        self.logger.error(f"[TOOL ERROR] {tool_name}: {str(error)}")
    
    # Agent events
    def on_agent_action(self, action, **kwargs):
        """Log when an agent decides on an action"""
        self.logger.debug(f"[AGENT ACTION] Tool: {action.tool}, Input: {action.tool_input}")  
        
    def on_agent_finish(self, finish, **kwargs):
        """Log when an agent completes its execution"""
        self.logger.debug(f"[AGENT FINISH] {finish.return_values}")


