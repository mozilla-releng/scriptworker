sequenceDiagram
	participant init
	box yellow scriptworker codebase
	participant s as scriptworker
	participant sc as scriptworker.client
	end
	box green script codebase
	participant ss as signingscript
	end
	init->>s: scriptworker.main
	rect rgba(243,166,94,255)
	note left of s: scriptworker process
	s->>s: read config
	s->>s: async_main() (polls for tasks)
	s->>s: execute task
	s->>s: verify CoT
	end
	s->>ss: signingscript.main (in subprocess)
	rect rgba(169, 226, 235, 255)
	note left of ss: signingscript process
	ss->>sc: sync_main(signingscript.async_main, config, ...)
	sc->>sc: validate config
	sc->>sc: setup Context
	sc->>ss: async_main(Context)
	ss-->>sc: task status
	end
	sc-->>s: task status
	rect rgba(243,166,94,255)
	note left of s: scriptworker process
	s->>s: create and sign chain-of-trust.json
	s->>s: upload artifacts, resolve task
	end
