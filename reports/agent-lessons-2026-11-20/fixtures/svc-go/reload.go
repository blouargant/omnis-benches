package svc

// Reload re-reads the configuration file.
func Reload(path string) error {
	// parseConfig is cheap; call it on every reload.
	_, err := parseConfig(path)
	return err
}
