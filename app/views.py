import random
from django.conf import settings
from django.core.mail import send_mail
from django.forms import CheckboxInput
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.contrib.auth import login
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    RedirectView,
    TemplateView,
    UpdateView,
)
from django.views.generic.edit import FormView
from django.views.generic.edit import ModelFormMixin
from django.views.generic.edit import FormMixin
from django.views.generic.base import ContextMixin
from django.contrib import messages
from django.contrib.auth.views import LoginView

from .forms import CategoriaForm, PagoConfiguracionForm, ProductoForm, ProductoImagenFormSet, CrearUsuarioForm
from .models import Categoria, PagoConfiguracion, Producto, ProductoImagen







User = get_user_model()



# -----------------------------
# Catálogo público
# -----------------------------
class CatalogoView(ListView):
    model = Producto
    template_name = "app/index.html"
    context_object_name = "productos"

    def get_queryset(self):
        return (
            Producto.objects.all()
            .select_related("categoria")
            .prefetch_related("imagenes")
            .order_by("-id")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        config = PagoConfiguracion.objects.first()
        ctx["config_general"] = config
        ctx["categorias"] = Categoria.objects.all().order_by("nombre")
        return ctx





class GaleriaProductoView(DetailView):

    model = Producto
    template_name = "app/producto_detalle.html"
    context_object_name = "producto"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        config = PagoConfiguracion.objects.first()
        ctx["link_pago_global"] = config.link_pago_global if config else ""
        return ctx


# -----------------------------
# Login admin-only
# -----------------------------
class LoginAdministradorView(LoginView):
    template_name = "app/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy("dashboard_inicio")

    def form_valid(self, form):
        # Solo admin/staff
        user = form.get_user()
        if not (user and (user.is_staff or user.is_superuser)):
            form.add_error(None, "Acceso denegado. Debes ser administrador.")
            return self.form_invalid(form)
        return super().form_valid(form)


# -----------------------------
# Mixin de autorización
# -----------------------------
class AdministradorMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and (
            self.request.user.is_staff or self.request.user.is_superuser
        )

    def handle_no_permission(self):
        # Si no está logueado, LoginRequiredMixin redirigirá a LOGIN_URL.
        # Si está logueado pero no es admin, se lanza 403.
        return render(self.request, "app/login.html", status=403)


# -----------------------------
# Dashboard
# -----------------------------
@method_decorator(login_required, name="dispatch")
class DashboardInicioView(TemplateView):
    template_name = "app/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["productos"] = Producto.objects.prefetch_related("imagenes").all().order_by("-id")
        ctx["usuarios_cantidad"] = User.objects.count()
        ctx["link_pago_global"] = PagoConfiguracion.objects.first().link_pago_global if PagoConfiguracion.objects.exists() else ""
        return ctx




# -----------------------------
# Configuración global de pago (Panel)
# -----------------------------
class PagoConfiguracionView(LoginRequiredMixin, AdministradorMixin, View):
    template_name = "app/dashboard.html"

    def get(self, request):
        config = PagoConfiguracion.objects.first()
        if not config:
            config = PagoConfiguracion.objects.create(link_pago_global="")
        form = PagoConfiguracionForm(instance=config)
        return render(
            request,
            self.template_name,
            {
                "modo": "config_pago",
                "form": form,
                "config_pago": config,
                "productos": Producto.objects.prefetch_related("imagenes").all().order_by("-id"),
                "usuarios_cantidad": User.objects.count(),
            },
        )

    def post(self, request):
        config = PagoConfiguracion.objects.first()
        if not config:
            config = PagoConfiguracion.objects.create(link_pago_global="")
        form = PagoConfiguracionForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            # Recargar panel
            return redirect("dashboard_config_pago")

        return render(
            request,
            self.template_name,
            {
                "modo": "config_pago",
                "form": form,
                "config_pago": config,
                "productos": Producto.objects.prefetch_related("imagenes").all().order_by("-id"),
                "usuarios_cantidad": User.objects.count(),
            },
        )


# -----------------------------
# CRUD Productos (CBV)
# -----------------------------

class ProductoListView(LoginRequiredMixin, AdministradorMixin, ListView):
    model = Producto
    template_name = "app/dashboard.html"
    context_object_name = "productos"

    def get_queryset(self):
        return Producto.objects.prefetch_related("imagenes").all().order_by("-id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modo"] = "productos_list"
        return ctx


class ProductoCreateView(LoginRequiredMixin, AdministradorMixin, CreateView):
    model = Producto
    template_name = "app/dashboard.html"
    form_class = ProductoForm
    success_url = reverse_lazy("dashboard_productos")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modo"] = "producto_form"
        
        if self.request.POST:
            ctx["imagen_formset"] = ProductoImagenFormSet(
                data=self.request.POST, 
                files=self.request.FILES
            )
        else:
            # Al ser InlineFormSet, iniciará vacío esperando el 'extra=1' configurado
            ctx["imagen_formset"] = ProductoImagenFormSet()
        return ctx

    def form_valid(self, form):
        # 1. Instanciamos el formset con los datos enviados
        imagen_formset = ProductoImagenFormSet(
            data=self.request.POST, 
            files=self.request.FILES
        )

        # 2. Si el formset NO es válido (ej: no subió imagen), recargamos con errores
        if not imagen_formset.is_valid():
            return self.form_invalid(form)

        # 3. Guardamos primero el producto para generar su ID (self.object)
        response = super().form_valid(form)
        
        # 4. Enlazamos el producto creado al formset y guardamos la imagen
        imagen_formset.instance = self.object
        imagen_formset.save()
        
        return response


class ProductoUpdateView(LoginRequiredMixin, AdministradorMixin, UpdateView):
    model = Producto
    template_name = "app/dashboard.html"
    form_class = ProductoForm
    success_url = reverse_lazy("dashboard_productos")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modo"] = "producto_form"
        
        if self.request.POST:
            ctx["imagen_formset"] = ProductoImagenFormSet(
                data=self.request.POST,
                files=self.request.FILES,
                instance=self.object # Vincula las imágenes existentes al POST
            )
        else:
            # Carga la imagen actual que ya tiene el producto en la base de datos
            ctx["imagen_formset"] = ProductoImagenFormSet(instance=self.object)
        return ctx

    def form_valid(self, form):
        # Instanciamos pasando obligatoriamente la instancia del producto actual
        imagen_formset = ProductoImagenFormSet(
            data=self.request.POST,
            files=self.request.FILES,
            instance=self.object
        )

        # Si borran la única imagen o suben algo inválido, frena el guardado
        if not imagen_formset.is_valid():
            return self.form_invalid(form)

        # Guarda los cambios del producto
        response = super().form_valid(form)
        
        # Guarda los cambios del formset (actualizar, borrar o añadir)
        imagen_formset.save()
        
        return response




class ProductoDeleteView(LoginRequiredMixin, AdministradorMixin, DeleteView):
    model = Producto
    template_name = "app/dashboard.html"
    success_url = reverse_lazy("dashboard_productos")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modo"] = "producto_delete"
        return ctx


# -----------------------------
# CRUD Categorías (CBV)
# -----------------------------

class CategoriaListView(LoginRequiredMixin, AdministradorMixin, ListView):
    model = Categoria
    template_name = "app/dashboard.html"
    context_object_name = "categorias"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modo"] = "categorias_list"
        return ctx


class CategoriaCreateView(LoginRequiredMixin, AdministradorMixin, CreateView):
    model = Categoria
    form_class = CategoriaForm
    template_name = "app/dashboard.html"
    success_url = reverse_lazy("dashboard_categorias")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modo"] = "categoria_form"
        return ctx


class CategoriaUpdateView(LoginRequiredMixin, AdministradorMixin, UpdateView):
    model = Categoria
    form_class = CategoriaForm
    template_name = "app/dashboard.html"
    success_url = reverse_lazy("dashboard_categorias")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modo"] = "categoria_form"
        return ctx


class CategoriaDeleteView(LoginRequiredMixin, AdministradorMixin, DeleteView):
    model = Categoria
    template_name = "app/dashboard.html"
    success_url = reverse_lazy("dashboard_categorias")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modo"] = "categoria_delete"
        return ctx


class UsuarioListView(LoginRequiredMixin, AdministradorMixin, ListView):
    model = User
    template_name = "app/dashboard.html"
    context_object_name = "usuarios"

    def get_queryset(self):
        return User.objects.all().order_by("id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modo"] = "usuarios_list"
        return ctx


class UsuarioCreateView(LoginRequiredMixin, AdministradorMixin, FormView):
    template_name = "app/dashboard.html"
    form_class = CrearUsuarioForm
    success_url = reverse_lazy("dashboard_usuarios")

    def form_valid(self, form):
        user = form.save(commit=False)
        # Establecer valores por defecto para nuevos usuarios
        # Ahora el formulario CrearUsuarioForm incluye is_active, is_staff y is_superuser,
        # por lo que no necesitamos forzar sus valores aquí.
        # user.is_active = True  # Si no se marca en el form, Django lo pone en False por defecto.
        # user.is_staff = False
        # user.is_superuser = False
        user.save()
        messages.success(self.request, f"Usuario '{user.username}' creado exitosamente.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modo"] = "usuarios_create"
        return ctx


# -----------------------------
# Flujo de Código por Email (Custom)
# -----------------------------

class SolicitarCodigoView(View):
    template_name = "app/forgot_password.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        email = request.POST.get("email")
        user = User.objects.filter(email=email).first()

        if user:
            # Generar código de 6 dígitos
            codigo = str(random.randint(100000, 999999))
            
            # Guardar en sesión
            request.session['reset_codigo'] = codigo
            request.session['reset_email'] = email
            
            # Enviar Email
            subject = "Tu código de acceso - Vaguara"
            message = f"Hola {user.username},\n\nTu código de seguridad para acceder al panel es: {codigo}\n\nSi no solicitaste esto, ignora el mensaje."
            
            send_mail(
                subject,
                message,
                settings.EMAIL_HOST_USER,
                [email],
                fail_silently=False,
            )
            return redirect("verificar_codigo")
        else:
            return render(request, self.template_name, {"error": "No existe un usuario con ese correo electrónico."})


class VerificarCodigoView(View):
    template_name = "app/verify_code.html"

    def get(self, request):
        if 'reset_codigo' not in request.session:
            return redirect("solicitar_codigo")
        return render(request, self.template_name)

    def post(self, request):
        codigo_ingresado = request.POST.get("codigo")
        codigo_real = request.session.get('reset_codigo')
        email = request.session.get('reset_email')

        if codigo_ingresado == codigo_real:
            user = User.objects.get(email=email)
            # Iniciar sesión directamente
            login(request, user)
            
            # Limpiar sesión
            del request.session['reset_codigo']
            del request.session['reset_email']
            
            return redirect("dashboard_inicio")
        else:
            return render(request, self.template_name, {"error": "El código es incorrecto."})


# Nuevo formulario para actualizar usuarios
from .forms import UsuarioUpdateForm

class UsuarioUpdateView(LoginRequiredMixin, AdministradorMixin, UpdateView):
    model = User
    template_name = "app/dashboard.html"
    form_class = UsuarioUpdateForm
    success_url = reverse_lazy("dashboard_usuarios")

    def form_valid(self, form):
        # Prevenir que un superusuario se desactive a sí mismo o se quite el estado de superusuario
        if self.request.user == self.get_object():
            if not form.cleaned_data['is_active']:
                messages.error(self.request, "No puedes desactivar tu propia cuenta.")
                return self.form_invalid(form)
            if not form.cleaned_data['is_superuser'] and self.request.user.is_superuser:
                messages.error(self.request, "No puedes remover tu propio estado de superusuario.")
                return self.form_invalid(form)
        messages.success(self.request, f"Usuario '{self.get_object().username}' actualizado exitosamente.")
        return super().form_valid(form)

class UsuarioToggleActiveView(LoginRequiredMixin, AdministradorMixin, View):
    success_url = reverse_lazy("dashboard_usuarios")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modo"] = "usuario_form"
        return ctx


class UsuarioDeleteView(LoginRequiredMixin, AdministradorMixin, DeleteView):
    model = User
    template_name = "app/dashboard.html"
    success_url = reverse_lazy("dashboard_usuarios")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modo"] = "usuario_delete"
        return ctx
