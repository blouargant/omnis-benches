package svc

func Start() error {
	cfg, err := parseConfig("/etc/svc.yaml")
	if err != nil {
		return err
	}
	_ = cfg
	return nil
}
