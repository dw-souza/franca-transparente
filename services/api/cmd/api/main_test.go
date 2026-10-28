package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHealthz(t *testing.T) {
	rec := httptest.NewRecorder()
	novoRoteador().ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/healthz", nil))

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, esperado 200", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "application/json" {
		t.Errorf("Content-Type = %q, esperado application/json", ct)
	}
	var corpo map[string]string
	if err := json.NewDecoder(rec.Body).Decode(&corpo); err != nil {
		t.Fatalf("corpo não é JSON: %v", err)
	}
	if corpo["status"] != "ok" {
		t.Errorf("status no corpo = %q, esperado ok", corpo["status"])
	}
}

func TestRotasDesconhecidasEMetodoErrado(t *testing.T) {
	casos := []struct {
		metodo, caminho string
		esperado        int
	}{
		{http.MethodPost, "/healthz", http.StatusMethodNotAllowed},
		{http.MethodGet, "/nao-existe", http.StatusNotFound},
	}
	for _, c := range casos {
		rec := httptest.NewRecorder()
		novoRoteador().ServeHTTP(rec, httptest.NewRequest(c.metodo, c.caminho, nil))
		if rec.Code != c.esperado {
			t.Errorf("%s %s: status = %d, esperado %d", c.metodo, c.caminho, rec.Code, c.esperado)
		}
	}
}
