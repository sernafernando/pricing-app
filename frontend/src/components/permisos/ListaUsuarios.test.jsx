import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ListaUsuarios from './ListaUsuarios';

// Out of id order on purpose: the list must not depend on the API order.
const USUARIOS = [
  { id: 12, nombre: 'Carla Díaz', username: 'zeta', email: 'carla@x.com', rol: 'VENTAS', activo: true },
  { id: 3, nombre: 'Beto Gómez', username: 'beto', email: 'beto@x.com', rol: 'ADMIN', activo: false },
  { id: 7, nombre: 'Ána Pérez', username: 'ana', email: 'ana@x.com', rol: 'PRICING', activo: true },
  { id: 9, nombre: 'Diego Ruiz', username: 'diego', email: 'diego@x.com', rol: 'ADMIN', activo: true },
];

const renderLista = (usuarios = USUARIOS) =>
  render(<ListaUsuarios usuarios={usuarios} seleccionadoId={null} overridesSeleccionado={null} onSeleccionar={vi.fn()} />);

// Each row is identified by the user name it shows, not by its CSS-module class.
const nombresEnOrden = (usuarios = USUARIOS) =>
  within(screen.getByRole('list', { name: 'Usuarios del sistema' }))
    .getAllByRole('button')
    .map((fila) => usuarios.find((u) => within(fila).queryByText(u.nombre)).nombre);

const ordenarPor = () => screen.getByRole('combobox', { name: 'Ordenar por' });

describe('ListaUsuarios sorting', () => {
  it('orders by user id (creation order) by default', () => {
    renderLista();

    expect(ordenarPor()).toHaveDisplayValue('ID (creación)');
    expect(nombresEnOrden()).toEqual(['Beto Gómez', 'Ána Pérez', 'Diego Ruiz', 'Carla Díaz']);
  });

  it('orders by name ignoring accents and case', async () => {
    const user = userEvent.setup();
    renderLista();

    await user.selectOptions(ordenarPor(), 'Nombre');

    expect(nombresEnOrden()).toEqual(['Ána Pérez', 'Beto Gómez', 'Carla Díaz', 'Diego Ruiz']);
  });

  it('orders by username', async () => {
    const user = userEvent.setup();
    renderLista();

    await user.selectOptions(ordenarPor(), 'Usuario');

    expect(nombresEnOrden()).toEqual(['Ána Pérez', 'Beto Gómez', 'Diego Ruiz', 'Carla Díaz']);
  });

  it('orders by role, then by name within a role', async () => {
    const user = userEvent.setup();
    renderLista();

    await user.selectOptions(ordenarPor(), 'Rol');

    expect(nombresEnOrden()).toEqual(['Beto Gómez', 'Diego Ruiz', 'Ána Pérez', 'Carla Díaz']);
  });

  it('orders by status with active users first, then by name', async () => {
    const user = userEvent.setup();
    renderLista();

    await user.selectOptions(ordenarPor(), 'Estado');

    expect(nombresEnOrden()).toEqual(['Ána Pérez', 'Carla Díaz', 'Diego Ruiz', 'Beto Gómez']);
  });

  it('reverses the order with the direction button and keeps it across criteria', async () => {
    const user = userEvent.setup();
    renderLista();

    await user.click(screen.getByRole('button', { name: 'Orden ascendente' }));

    expect(screen.getByRole('button', { name: 'Orden descendente' })).toBeInTheDocument();
    expect(nombresEnOrden()).toEqual(['Carla Díaz', 'Diego Ruiz', 'Ána Pérez', 'Beto Gómez']);

    await user.selectOptions(ordenarPor(), 'Nombre');

    expect(nombresEnOrden()).toEqual(['Diego Ruiz', 'Carla Díaz', 'Beto Gómez', 'Ána Pérez']);
  });

  it('sorts the search results', async () => {
    const user = userEvent.setup();
    renderLista();

    await user.selectOptions(ordenarPor(), 'Nombre');
    await user.type(screen.getByPlaceholderText('Buscar usuario...'), 'admin');

    expect(nombresEnOrden()).toEqual(['Beto Gómez', 'Diego Ruiz']);
  });

  it('does not reorder the array it receives', async () => {
    const user = userEvent.setup();
    const usuarios = [...USUARIOS];
    renderLista(usuarios);

    await user.selectOptions(ordenarPor(), 'Nombre');

    expect(usuarios.map((u) => u.id)).toEqual([12, 3, 7, 9]);
  });

  it('sorts users with a missing username or role first instead of failing', async () => {
    const user = userEvent.setup();
    const usuarios = [...USUARIOS, { id: 20, nombre: 'Eva Sin Datos', username: null, email: null, rol: null, activo: true }];
    renderLista(usuarios);

    await user.selectOptions(ordenarPor(), 'Usuario');
    expect(nombresEnOrden(usuarios)[0]).toBe('Eva Sin Datos');

    await user.selectOptions(ordenarPor(), 'Rol');
    expect(nombresEnOrden(usuarios)[0]).toBe('Eva Sin Datos');
  });
});
