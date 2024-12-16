import { ScheduledEvent, ExecutionContext } from '@cloudflare/workers-types';

export interface Env {
	// If you need any environment variables, declare them here
}

export default {
	// Add fetch handler for HTTP requests
	async fetch(request: Request, env: Env, ctx: ExecutionContext) {
		return new Response('Keepalive worker is running!', { status: 200 });
	},

	// Existing scheduled handler
	async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext) {
		try {
			const response = await fetch('https://flymebaby-python.onrender.com');
			if (response.ok) {
				console.log('Successfully pinged backend server');
			} else {
				console.error(`Failed to ping backend: ${response.status}`);
			}
		} catch (error) {
			console.error('Error pinging backend:', error);
		}
	},
};
