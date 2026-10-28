// Command api é o backend REST do Painel de Transparência de Franca.
//
// Esqueleto inicial: só /healthz e desligamento gracioso. As rotas de dados entram em
// internal/handler (HTTP) → internal/service (regras) → internal/repository (SQL/pgx).
package main

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	porta := os.Getenv("API_PORT")
	if porta == "" {
		porta = "8080"
	}

	srv := &http.Server{
		Addr:              ":" + porta,
		Handler:           novoRoteador(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      30 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	go func() {
		logger.Info("api ouvindo", "addr", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("servidor parou", "erro", err)
			os.Exit(1)
		}
	}()

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutdownCtx)
	logger.Info("api encerrada")
}

// novoRoteador monta as rotas HTTP; separado de main para ser testável com httptest.
func novoRoteador() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	})
	return mux
}
