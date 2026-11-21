package limiter

import "time"

// Bucket is a token bucket: it refills `rate` tokens per second up to `burst`.
type Bucket struct {
	rate   float64
	burst  int
	tokens float64
	last   time.Time
}

// New returns a full bucket.
func New(rate float64, burst int) *Bucket {
	return &Bucket{rate: rate, burst: burst, tokens: float64(burst), last: time.Now()}
}

// Allow takes one token if one is available.
func (b *Bucket) Allow(now time.Time) bool {
	b.tokens += now.Sub(b.last).Seconds() * b.rate
	if b.tokens > float64(b.burst) {
		b.tokens = float64(b.burst)
	}
	b.last = now
	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}
