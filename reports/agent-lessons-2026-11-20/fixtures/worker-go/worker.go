package worker

import "log"

var failures int

func run(id int, job func() error) {
	err := job()
	if err != nil {
		log.Printf("job %d failed: %v", id, err)
		return
	}
	log.Printf("job %d done", id)
}
