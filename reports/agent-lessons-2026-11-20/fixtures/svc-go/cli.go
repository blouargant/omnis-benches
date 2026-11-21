package svc

func Check(paths []string) int {
	bad := 0
	for _, p := range paths {
		if _, err := parseConfig(p); err != nil {
			bad++
		}
	}
	return bad
}
