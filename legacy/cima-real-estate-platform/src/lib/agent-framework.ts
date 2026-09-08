// Hermes Agent Framework
// Base class for all specialized agents

export abstract class Agent {
  abstract name: string;
  abstract description: string;
  
  // Common agent methods
  log(message: string): void {
    console.log(`[${this.name}] ${message}`);
  }
  
  async initialize(): Promise<void> {
    this.log('Initializing...');
  }
  
  async shutdown(): Promise<void> {
    this.log('Shutting down...');
  }
  
  // Error handling
  protected handleError(error: unknown, context: string): never {
    const errorMessage = error instanceof Error ? error.message : String(error);
    throw new Error(`[${this.name}] Error in ${context}: ${errorMessage}`);
  }
}