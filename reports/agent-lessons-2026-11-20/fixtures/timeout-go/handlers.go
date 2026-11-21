package api

import (
	"context"
	"net/http"
	"time"
)

func serve(ctx context.Context, w http.ResponseWriter, kind string) {
	select {
	case <-ctx.Done():
		http.Error(w, kind+": timeout", http.StatusGatewayTimeout)
	default:
		w.WriteHeader(http.StatusOK)
	}
}

func handleDownload(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	serve(ctx, w, "download")
}

func handleUpload(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	serve(ctx, w, "upload")
}
