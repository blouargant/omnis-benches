package svc

import "os"

type Config struct{ Port string }

func parseConfig(path string) (*Config, error) {
	if _, err := os.Stat(path); err != nil {
		return nil, err
	}
	return &Config{Port: "8080"}, nil
}
